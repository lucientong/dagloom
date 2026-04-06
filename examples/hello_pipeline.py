#!/usr/bin/env python3
"""Hello Pipeline — A minimal Dagloom example.

Run with:
    python examples/hello_pipeline.py
"""

from dagloom import node


@node
def greet(name: str) -> str:
    """Create a greeting message."""
    return f"Hello, {name}!"


@node
def shout(message: str) -> str:
    """Convert message to uppercase."""
    return message.upper()


@node
def add_emoji(message: str) -> str:
    """Add emoji to the message."""
    return f"🎉 {message} 🎉"


# Build DAG with >> operator
pipeline = greet >> shout >> add_emoji

if __name__ == "__main__":
    result = pipeline.run(name="World")
    print(result)
    # Output: 🎉 HELLO, WORLD! 🎉

    print("\nPipeline structure:")
    print(pipeline.visualize())
