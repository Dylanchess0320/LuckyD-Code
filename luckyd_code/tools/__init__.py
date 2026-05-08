from .registry import ToolRegistry, Tool
from .file_ops import ReadTool, WriteTool, EditTool, GlobTool, GrepTool
from .bash import BashTool
from .datetime_tool import DateTimeTool
from .web import WebFetchTool, WebSearchTool
from .browser import (
    BrowserNavigateTool, BrowserClickTool, BrowserTypeTool,
    BrowserSnapshotTool, BrowserScreenshotTool,
    BrowserEvaluateTool, BrowserCloseTool, OpenInBrowserTool,
    BrowserStateTool, BrowserEmulateTool, BrowserInterceptTool,
    BrowserTraceTool, BrowserToggleHeadlessTool,
)
from .git_tools import (
    GitStatusTool, GitDiffTool, GitLogTool,
    GitCommitTool, GitAddTool, GitBranchTool,
    GitPRTool, GitPushTool,
)
from .git_worktree import GitWorktreeTool
from .agent_tools import SubAgentTool, AgentHandoffTool
from .brain_tools import BrainSearchTool, BrainStatusTool
from .youtube import YouTubePlaylistTool
from .game_gen import GameGenTool
from .project_gen import ProjectGenTool
from .readme_gen import ReadmeGenTool
from .dockerfile_gen import DockerfileGenTool

__all__ = [
    "ToolRegistry", "Tool",
    "ReadTool", "WriteTool", "EditTool", "GlobTool", "GrepTool",
    "BashTool", "DateTimeTool",
    "WebFetchTool", "WebSearchTool",
    "BrowserNavigateTool", "BrowserClickTool", "BrowserTypeTool",
    "BrowserSnapshotTool", "BrowserScreenshotTool",
    "BrowserEvaluateTool", "BrowserCloseTool", "OpenInBrowserTool",
    "BrowserStateTool", "BrowserEmulateTool", "BrowserInterceptTool",
    "BrowserTraceTool", "BrowserToggleHeadlessTool",
    "GitStatusTool", "GitDiffTool", "GitLogTool",
    "GitCommitTool", "GitAddTool", "GitBranchTool",
    "GitPRTool", "GitPushTool",
    "GitWorktreeTool",
    "SubAgentTool", "AgentHandoffTool",
    "BrainSearchTool", "BrainStatusTool",
    "YouTubePlaylistTool",
    "GameGenTool",
    "ProjectGenTool",
    "ReadmeGenTool",
    "DockerfileGenTool",
    "get_default_registry",
]


def get_default_registry():
    registry = ToolRegistry()
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(BashTool())
    registry.register(DateTimeTool())
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())
    registry.register(GitStatusTool())
    registry.register(GitDiffTool())
    registry.register(GitLogTool())
    registry.register(GitCommitTool())
    registry.register(GitAddTool())
    registry.register(GitBranchTool())
    registry.register(GitPRTool())
    registry.register(GitPushTool())
    registry.register(GitWorktreeTool())
    registry.register(SubAgentTool())
    registry.register(AgentHandoffTool())
    registry.register(BrainSearchTool())
    registry.register(BrainStatusTool())
    registry.register(BrowserNavigateTool())
    registry.register(BrowserClickTool())
    registry.register(BrowserTypeTool())
    registry.register(BrowserSnapshotTool())
    registry.register(BrowserScreenshotTool())
    registry.register(BrowserEvaluateTool())
    registry.register(BrowserCloseTool())
    registry.register(OpenInBrowserTool())
    registry.register(BrowserStateTool())
    registry.register(BrowserEmulateTool())
    registry.register(BrowserInterceptTool())
    registry.register(BrowserTraceTool())
    registry.register(BrowserToggleHeadlessTool())
    registry.register(YouTubePlaylistTool())
    registry.register(GameGenTool())
    registry.register(ProjectGenTool())
    registry.register(ReadmeGenTool())
    registry.register(DockerfileGenTool())

    # Load external plugins from ~/.claude/plugins/
    try:
        from ..plugins import load_all_plugins
        n = load_all_plugins(registry)
        if n:
            logger = __import__("logging").getLogger("luckyd_code")
            logger.info("Loaded %d plugin(s)", n)
    except Exception:
        logger = __import__("logging").getLogger("luckyd_code")
        logger.warning("Failed to load plugins", exc_info=True)

    return registry
