"""Pytest configuration. Sets test database before any imports."""
import os

# Use in-memory SQLite for all tests so they never touch production data.
# Must run before src.data.database (or any module that imports it) is loaded.
os.environ["INVESTMENT_AGENT_USE_INMEMORY_DB"] = "1"
