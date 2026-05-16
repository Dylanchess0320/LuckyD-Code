import os, sys, random, math
os.environ.setdefault("SDL_VIDEODRIVER", "windib")
import pygame

# ---------------------------------------------------------------------------
# Config (placeholders will be replaced by caller)
# ---------------------------------------------------------------------------
THEME_COLOR = "#00FFCC"
DIFF_MULT = 1.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

FG = _hex(THEME_COLOR)

def beep(freq=440, ms=60, vol=0.12):
    try:
        n = int(22050 * ms / 1000)
        buf = bytearray(n)
        for i in range(n):
            buf[i] = (127 if (i * freq * 2 // 22050) % 2 == 0 else 129) & 0xFF
        s = pygame.mixer.Sound(buffer=bytes(buf))
        s.set_volume(vol)
        s.play()
    except Exception:
        pass

def save_high_score(score):
    try:
        with open("void_blaster_highscore.txt", "w") as f:
            f.write(str(score))
    except:
        pass

def load_high_score():
    try:
        with open("void_blaster_highscore.txt", "r") as f:
            return int(f.read().strip())
    except:
        return 0

# ---------------------------------------------------------------------------
# Game constants (scaled by DIFF_MULT where appropriate)
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 800, 600
PLAYER_SPEED = 5
BULLET_SPEED = 8
ENEMY_BASE_SPEED = 1.5 * DIFF_MULT
BULLET_COOLDOWN = 10
RAPID_FIRE_COOLDOWN = 4
POWERUP_DURATION = 300
SHIELD_DURATION = 600
SCREEN_SHAKE_DURATION = 8
WAVE_DELAY = 120          # frames between waves
ENEMIES_PER_WAVE_BASE = 5
ENEMIES_PER_WAVE_INC = 3

# States
START = 0
PLAYING = 1
WAVE_TRANSITION = 2
GAMEOVER = 3

# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------
class Player(pygame.sprite.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pygame.Surface((30, 30), pygame.SRCALPHA)
        self.draw_ship()
        self.rect = self.image.get_rect(center=(WIDTH//2, HEIGHT-40))
        self.radius = 12
        self.speed = PLAYER_SPEED
        self.shielded = False
        self.shield_timer = 0

    def draw_ship(self):
        self.image.fill((0,0,0,0))
        # triangle ship (neon)
        pygame.draw.polygon(self.image, FG, [(15, 2), (4, 28), (26, 28)])
        pygame.draw.polygon(self.image, (255,255,255), [(15, 5), (8, 25), (22, 25)], 1)
        if self.shielded:
            pygame.draw.circle(self.image, (100,255,100), (15,15), 18, 2)

    def update(self):
        keys = pygame.key.get_pressed()
        dx = dy = 0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            dx = -self.speed
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            dx = self.speed
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            dy = -self.speed
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            dy = self.speed
        self.rect.x += dx
        self.rect.y += dy
        self.rect.clamp_ip(pygame.Rect(0, 0, WIDTH, HEIGHT))

        if self.shielded:
            self.shield_timer -= 1
            if self.shield_timer <= 0:
                self.shielded = False
                self.draw_ship()

    def activate_shield(self, frames):
        self.shielded = True
        self.shield_timer = frames
        self.draw_ship()

class Bullet(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.image = pygame.Surface((4, 14))
        self.image.fill(FG)
        self.rect = self.image.get_rect(center=(x, y))
        self.speed = BULLET_SPEED

    def update(self):
        self.rect.y -= self.speed
        if self.rect.bottom < 0:
            self.kill()

class Enemy(pygame.sprite.Sprite):
    def __init__(self, wave):
        super().__init__()
        size = random.randint(20, 35)
        self.image = pygame.Surface((size, size), pygame.SRCALPHA)
        # neon alien shape
        color = FG
        pygame.draw.polygon(self.image, color, [(size//2, 2), (2, size-2), (size-2, size-2)])
        pygame.draw.circle(self.image, (255,255,255), (size//2, size//2), size//3, 1)
        self.rect = self.image.get_rect(center=(random.randint(20, WIDTH-20), -size))
        self.speed_y = ENEMY_BASE_SPEED + wave * 0.2 * DIFF_MULT
        self.speed_x = random.choice([-1,1]) * random.uniform(0.5, 1.5)
        self.radius = size//2
        self.points = 100 + wave * 10

    def update(self):
        self.rect.y += self.speed_y
        self.rect.x += self.speed_x
        if self.rect.left < 0 or self.rect.right > WIDTH:
            self.speed_x *= -1
        if self.rect.top > HEIGHT + 40:
            self.kill()

class PowerUp(pygame.sprite.Sprite):
    def __init__(self, x, y, kind):
        super().__init__()
        self.kind = kind  # 'rapid', 'shield', 'multiplier'
        self.image = pygame.Surface((22, 22), pygame.SRCALPHA)
        # draw icon
        if kind == 'rapid':
            color = (255,255,0)
            label = 'R'
        elif kind == 'shield':
            color = (0,255,255)
            label = 'S'
        else:  # multiplier
            color = (255,165,0)
            label = 'M'
        pygame.draw.circle(self.image, color, (11,11), 10)
        pygame.draw.circle(self.image, (255,255,255), (11,11), 10, 1)
        font = pygame.font.Font(None, 18)
        txt = font.render(label, True, (0,0,0))
        self.image.blit(txt, txt.get_rect(center=(11,11)))
        self.rect = self.image.get_rect(center=(x, y))
        self.speed_y = 2 * DIFF_MULT

    def update(self):
        self.rect.y += self.speed_y
        if self.rect.top > HEIGHT:
            self.kill()

class Particle(pygame.sprite.Sprite):
    def __init__(self, x, y, color):
        super().__init__()
        self.size = random.randint(2, 6)
        self.image = pygame.Surface((self.size, self.size))
        self.image.fill(color)
        self.rect = self.image.get_rect(center=(x, y))
        self.vx = random.uniform(-4, 4)
        self.vy = random.uniform(-4, 4)
        self.life = random.randint(20, 40)

    def update(self):
        self.rect.x += self.vx
        self.rect.y += self.vy
        self.life -= 1
        if self.life <= 0:
            self.kill()
        else:
            alpha = max(0, int(255 * self.life / 40))
            self.image.set_alpha(alpha)

class Star:
    def __init__(self):
        self.x = random.randint(0, WIDTH)
        self.y = random.randint(0, HEIGHT)
        self.speed = random.uniform(0.2, 1.5)
        self.brightness = random.randint(100, 255)

    def update(self):
        self.y += self.speed
        if self.y > HEIGHT:
            self.y = 0
            self.x = random.randint(0, WIDTH)

    def draw(self, screen):
        pygame.draw.circle(screen, (self.brightness, self.brightness, self.brightness), (int(self.x), int(self.y)), 1)

# ---------------------------------------------------------------------------
# Main game function
# ---------------------------------------------------------------------------
def main():
    pygame.init()
    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=256)
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Void Blaster")
    clock = pygame.time.Clock()
    font_small = pygame.font.Font(None, 28)
    font_large = pygame.font.Font(None, 48)

    # Stars
    stars = [Star() for _ in range(100)]

    # Variables
    state = START
    score = 0
    high_score = load_high_score()
    wave = 0
    wave_timer = 0
    lives = 3
    rapid_fire = False
    rapid_timer = 0
    score_multiplier = False
    mult_timer = 0
    bullet_cooldown = 0
    shake_timer = 0
    shake_offset = [0, 0]

    # Groups
    all_sprites = pygame.sprite.Group()
    player = Player()
    all_sprites.add(player)
    bullets = pygame.sprite.Group()
    enemies = pygame.sprite.Group()
    powerups = pygame.sprite.Group()
    particles = pygame.sprite.Group()

    def spawn_wave():
        nonlocal wave
        wave += 1
        n = ENEMIES_PER_WAVE_BASE + (wave-1) * ENEMIES_PER_WAVE_INC
        for _ in range(n):
            e = Enemy(wave)
            enemies.add(e)
            all_sprites.add(e)

    def spawn_particles(x, y, color=FG):
        for _ in range(20):
            p = Particle(x, y, color)
            particles.add(p)
            all_sprites.add(p)

    def player_hit():
        nonlocal lives
        if player.shielded:
            player.shielded = False
            player.shield_timer = 0
            player.draw_ship()
            beep(200, 80, 0.2)
            spawn_particles(player.rect.center, (100,255,100))
            return
        lives -= 1
        if lives <= 0:
            state_change(GAMEOVER)
        else:
            # respawn with brief invincibility? Simple: reset position, remove shields
            player.rect.center = (WIDTH//2, HEIGHT-40)
            player.shielded = False
            player.shield_timer = 0
            player.draw_ship()
            # screen shake
            shake_timer = SCREEN_SHAKE_DURATION
            beep(120, 200, 0.3)

    def state_change(new_state):
        nonlocal wave_timer, state
        state = new_state
        if new_state == START:
            pass
        elif new_state == WAVE_TRANSITION:
            wave_timer = WAVE_DELAY
        elif new_state == PLAYING:
            pass
        elif new_state == GAMEOVER:
            nonlocal high_score
            if score > high_score:
                high_score = score
                save_high_score(high_score)
            beep(800, 100, 0.2)

    # Start screen loop
    running = True
    while running:
        dt = clock.tick(60)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                return
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    return
                if state == START:
                    if event.key == pygame.K_SPACE:
                        # Reset game
                        score = 0
                        wave = 0
                        lives = 3
                        rapid_fire = False
                        rapid_timer = 0
                        score_multiplier = False
                        mult_timer = 0
                        bullet_cooldown = 0
                        shake_timer = 0
                        player.rect.center = (WIDTH//2, HEIGHT-40)
                        player.shielded = False
                        player.shield_timer = 0
                        player.draw_ship()
                        bullets.empty()
                        enemies.empty()
                        powerups.empty()
                        particles.empty()
                        all_sprites.empty()
                        all_sprites.add(player)
                        state_change(WAVE_TRANSITION)
                        beep(440, 50, 0.1)

        # Update stars
        for s in stars:
            s.update()

        # Draw everything
        screen.fill((5,5,15))
        for s in stars:
            s.draw(screen)

        if state == START:
            title = font_large.render("VOID BLASTER", True, FG)
            screen.blit(title, title.get_rect(center=(WIDTH//2, HEIGHT//2 - 60)))
            instru = font_small.render("Press SPACE to Start", True, FG)
            screen.blit(instru, instru.get_rect(center=(WIDTH//2, HEIGHT//2)))
            high_txt = font_small.render(f"High Score: {high_score}", True, FG)
            screen.blit(high_txt, high_txt.get_rect(center=(WIDTH//2, HEIGHT//2 + 40)))
            esc_txt = font_small.render("ESC to Quit", True, FG)
            screen.blit(esc_txt, esc_txt.get_rect(center=(WIDTH//2, HEIGHT//2 + 70)))

        elif state == WAVE_TRANSITION:
            wave_timer -= 1
            if wave_timer <= 0:
                spawn_wave()
                state_change(PLAYING)
            else:
                # wave announcement
                if wave_timer % 30 < 15:  # blink
                    wave_txt = font_large.render(f"Wave {wave}", True, FG)
                    screen.blit(wave_txt, wave_txt.get_rect(center=(WIDTH//2, HEIGHT//2)))

        elif state == PLAYING:
            # Handle input
            keys = pygame.key.get_pressed()
            if keys[pygame.K_SPACE]:
                if bullet_cooldown <= 0:
                    b = Bullet(player.rect.centerx, player.rect.top)
                    bullets.add(b)
                    all_sprites.add(b)
                    bullet_cooldown = RAPID_FIRE_COOLDOWN if rapid_fire else BULLET_COOLDOWN
                    beep(880, 30, 0.05)
            if bullet_cooldown > 0:
                bullet_cooldown -= 1

            # Powerup timers
            if rapid_fire:
                rapid_timer -= 1
                if rapid_timer <= 0:
                    rapid_fire = False
                    bullet_cooldown = min(bullet_cooldown, BULLET_COOLDOWN)
            if score_multiplier:
                mult_timer -= 1
                if mult_timer <= 0:
                    score_multiplier = False

            # Update all sprites
            player.update()
            bullets.update()
            enemies.update()
            powerups.update()
            particles.update()

            # Collisions: bullets vs enemies
            hits = pygame.sprite.groupcollide(bullets, enemies, True, False)
            for bullet, hit_list in hits.items():
                for enemy in hit_list:
                    points = enemy.points * (2 if score_multiplier else 1)
                    score += points
                    spawn_particles(enemy.rect.center, FG)
                    # chance to drop powerup
