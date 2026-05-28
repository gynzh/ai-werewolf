from __future__ import annotations

import tempfile
import time
import unittest

from ai_werewolf.configs.boards import build_config
from ai_werewolf.web.server import WebGameSession, WebSessionManager


class TestWebSessions(unittest.TestCase):
    def test_web_sessions_have_unique_ids_and_artifact_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            s1 = WebGameSession(build_config(preset="6p", seed=1, human_players=[]), out_dir=d, session_id="alpha")
            s2 = WebGameSession(build_config(preset="6p", seed=1, human_players=[]), out_dir=d, session_id="beta")
            self.assertNotEqual(s1.session_id, s2.session_id)
            self.assertNotEqual(s1.out_dir, s2.out_dir)
            self.assertEqual(s1.log_path.name, "events.jsonl")
            self.assertEqual(s2.review_path.name, "review.json")

    def test_web_session_manager_tracks_default_and_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            manager = WebSessionManager()
            session = WebGameSession(build_config(preset="6p", seed=2, human_players=[]), out_dir=d, session_id="main")
            manager.add(session, start=False)
            self.assertEqual(manager.default_session_id, "main")
            self.assertIs(manager.get("main"), session)
            self.assertEqual(manager.list()[0]["session_id"], "main")
            self.assertEqual(manager.meta()["session_count"], 1)

    def test_web_session_outputs_are_saved_under_session_directory(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            session = WebGameSession(
                build_config(preset="6p", seed=3, human_players=[]),
                out_dir=d,
                session_id="smoke",
                public_event_delay_seconds=0,
            )
            session.start()
            deadline = time.time() + 5
            while not session.done and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(session.done)
            self.assertIsNone(session.error)
            self.assertTrue(session.log_path.exists())
            self.assertTrue(session.review_path.exists())
            self.assertTrue(session.html_path.exists())
            self.assertEqual(session.log_path.parent.name, "session_smoke")


if __name__ == "__main__":
    unittest.main()
