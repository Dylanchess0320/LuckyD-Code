"""Example plugin: Hello World

The simplest possible LuckyD Code plugin.

Install:
    cp hello_world.py ~/.luckyd-code/plugins/
    # then inside ldc: /plugins reload
"""

from luckyd_code.tools.registry import Tool


class HelloWorldTool(Tool):
    name = "HelloWorld"
    description = "Greets the user by name. Example plugin — replace with your own logic."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name to greet",
            },
        },
        "required": [],
    }

    def run(self, name: str = "world") -> str:
        return f"Hello, {name}! The plugin system is working."


def register(registry) -> None:
    registry.register(HelloWorldTool())
