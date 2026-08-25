"""The interchangeable brains. Each exposes the same handle()/greeting()/name.

Import them lazily, never here: pulling in every brain would drag in every
provider SDK, and a missing optional package would break the whole core.
"""
