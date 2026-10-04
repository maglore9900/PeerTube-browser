"""Throwaway probe for the phase 2 checkpoint: what quote() gives for the snapshot's video_id column."""
import sqlite3


def test_probe():
    conn = sqlite3.connect(":memory:")
    print("quote", conn.execute("SELECT quote('z'), quote(NULL), quote(1), quote(1.0)").fetchone())
