"""
LuckyD Code Example — Web Scraper Agent
========================================
Demonstrates using LuckyD Code as a library to build an AI-powered web scraper.

The agent:
  1. Fetches a URL using the WebFetch tool
  2. Extracts structured data using the model
  3. Saves results to a local JSON file using the Write tool
  4. Prints a summary

Usage:
    python examples/web_scraper.py

Requirements:
    pip install luckyd-code
    Set DEEPSEEK_API_KEY in your environment or .env file.
"""

import json
import os
import sys

# Allow running from the repo root without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()


def run_scraper(url: str, output_file: str = "scraped_data.json") -> None:
    """Run an AI agent that scrapes a URL and saves structured data."""
    from luckyd_code.config import Config
    from luckyd_code.context import ConversationContext
    from luckyd_code.tools import get_default_registry
    from luckyd_code._agent_loop import run_agent_loop, RunConfig

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    # Build config
    config = Config()
    config.api_key = api_key
    config.base_url = "https://api.deepseek.com/v1"
    config.model = "deepseek-v4-flash"
    config.max_tokens = 4096
    config.temperature = 0.3
    config.system_prompt = (
        "You are a precise web scraping agent. "
        "When given a URL, fetch it, extract the most relevant information, "
        "and save it as clean, structured JSON. "
        "Always confirm the write succeeded."
    )

    # Set up context and registry
    context = ConversationContext(config.system_prompt)
    registry = get_default_registry()

    # The task
    task = f"""
Please do the following:
1. Fetch the webpage at: {url}
2. Extract the key information (title, main content summary, any links or data tables)
3. Write the results as structured JSON to: {output_file}
4. Report what you saved and how many items you extracted.
"""

    context.add_user_message(task)

    print(f"🕸️  Scraping: {url}")
    print(f"📄 Output:   {output_file}\n")

    # Stream output to console
    def on_text(chunk: str) -> None:
        print(chunk, end="", flush=True)

    def on_tool_start(name: str, idx: int, total: int) -> None:
        print(f"\n⚙️  [{idx}/{total}] Running tool: {name}")

    rc = RunConfig(
        max_turns=8,
        on_text=on_text,
        on_tool_start=on_tool_start,
        auto_save_memory=False,  # disable memory for this standalone script
    )

    result = run_agent_loop(
        context=context,
        config=config,
        tools=registry.list_tools(),
        registry=registry,
        run_config=rc,
    )

    print("\n\n✅ Done!")

    # Verify output file was created
    if os.path.exists(output_file):
        try:
            with open(output_file) as f:
                data = json.load(f)
            print(f"📦 Saved {output_file} ({len(str(data))} chars)")
        except json.JSONDecodeError:
            print(f"⚠️  Output file exists but isn't valid JSON — check {output_file}")
    else:
        print(f"⚠️  No output file found at {output_file}")


if __name__ == "__main__":
    # Default: scrape Hacker News front page
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com"
    output = sys.argv[2] if len(sys.argv) > 2 else "scraped_data.json"

    run_scraper(target_url, output)
