import json
import tempfile
import time
import unittest
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ai_werewolf.configs.boards import build_config, parse_player_ids, parse_roles
from ai_werewolf.engine.game_engine import run_game
from ai_werewolf.eval.leaderboard import build_leaderboard
from ai_werewolf.eval.review import build_review
from ai_werewolf.llm.output_parser import parse_action_json
from ai_werewolf.llm.prompt_builder import build_agent_prompt
from ai_werewolf.llm.openai_compatible_provider import OpenAICompatibleConfig, OpenAICompatibleProvider
from ai_werewolf.models.schema import Faction, Phase, Role
from ai_werewolf.rules.actions import ActionValidator
from ai_werewolf.models.schema import Action, GameState, PlayerState, GameConfig
from ai_werewolf.visibility.visibility_manager import VisibilityManager
from ai_werewolf.web.server import WebGameSession


class TestWerewolfCore(unittest.TestCase):
    def test_6p_game_runs_to_completion(self):
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "game.jsonl"
            state, store = run_game(seed=123, log_path=log_path)
            self.assertIn(state.winner, {Faction.GOOD.value, Faction.WOLVES.value})
            self.assertTrue(log_path.exists())
            self.assertGreater(len(store.events), 10)
            self.assertTrue(any(e.event_type == "game_ended" for e in store.events))

    def test_10p_standard_board_runs_with_hunter_and_guard(self):
        with tempfile.TemporaryDirectory() as d:
            config = build_config(preset="10p-standard", seed=222)
            state, store = run_game(config=config, log_path=Path(d) / "game.jsonl")
            roles = [p.role for p in state.players.values()]
            self.assertEqual(len(state.players), 10)
            self.assertIn(Role.HUNTER.value, roles)
            self.assertIn(Role.GUARD.value, roles)
            self.assertTrue(any(e.event_type == "guard_action_taken" for e in store.events))
            self.assertTrue(any(e.event_type == "game_ended" for e in store.events))

    def test_private_role_assignment_not_public_before_end(self):
        with tempfile.TemporaryDirectory() as d:
            _, store = run_game(seed=124, log_path=Path(d) / "game.jsonl")
            public_before_end = [e for e in store.events if e.visibility == "public" and e.event_type != "game_ended"]
            text = "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in public_before_end)
            for role in [Role.WEREWOLF.value, Role.SEER.value, Role.WITCH.value, Role.HUNTER.value, Role.GUARD.value]:
                self.assertNotIn(f'"role": "{role}"', text)

    def test_visibility_manager_builds_observations(self):
        with tempfile.TemporaryDirectory() as d:
            state, store = run_game(seed=125, log_path=Path(d) / "game.jsonl")
            visibility = VisibilityManager()
            for player_id in state.players:
                obs = visibility.build_observation(state, store, player_id)
                self.assertEqual(obs.player_id, player_id)
                self.assertEqual(obs.role, state.players[player_id].role)
                self.assertIsInstance(obs.public_history, list)

    def test_custom_roles_and_human_parser(self):
        roles = parse_roles("werewolf, seer, witch, hunter, guard, villager")
        self.assertEqual(roles, [Role.WEREWOLF.value, Role.SEER.value, Role.WITCH.value, Role.HUNTER.value, Role.GUARD.value, Role.VILLAGER.value])
        self.assertEqual(parse_player_ids("p1, P3"), ["P1", "P3"])
        config = build_config(roles=roles, seed=1, human_players=["P1"])
        self.assertEqual(config.player_count, 6)
        self.assertEqual(config.human_players, ["P1"])

    def test_hunter_shoot_action_validation_allows_dead_hunter(self):
        config = GameConfig(player_count=2, roles=[Role.HUNTER.value, Role.WEREWOLF.value])
        state = GameState(game_id="test", config=config, phase=Phase.HUNTER_SHOOT.value)
        state.players = {
            "P1": PlayerState("P1", 1, "1号", Role.HUNTER.value, Faction.GOOD.value, alive=False, skill_state={"bullet": True}),
            "P2": PlayerState("P2", 2, "2号", Role.WEREWOLF.value, Faction.WOLVES.value, alive=True),
        }
        ActionValidator().validate(state, Action("P1", "hunter_shoot", "P2"))


class TestWerewolfReportsAndExtensions(unittest.TestCase):
    def test_leaderboard_from_reviews(self):
        with tempfile.TemporaryDirectory() as d:
            reviews = []
            for seed in [301, 302, 303]:
                state, store = run_game(seed=seed, log_path=Path(d) / f"game_{seed}.jsonl")
                reviews.append(build_review(state, store))
            leaderboard = build_leaderboard(reviews)
            self.assertEqual(leaderboard["total_games"], 3)
            self.assertIn("overall", leaderboard)
            self.assertIn("role_survival", leaderboard)
            self.assertIn("by_version", leaderboard)

    def test_llm_prompt_and_parser_scaffold(self):
        with tempfile.TemporaryDirectory() as d:
            state, store = run_game(seed=404, log_path=Path(d) / "game.jsonl")
            visibility = VisibilityManager()
            player_id = next(iter(state.players))
            obs = visibility.build_observation(state, store, player_id)
            prompt = build_agent_prompt(obs)
            self.assertIn("只允许基于下面 JSON", prompt)
            self.assertIn("guard_protect", prompt)
            action = parse_action_json(player_id, '{"action_type":"vote","target_player_id":"P2","content":null,"reasoning_summary":"test","confidence":0.7}')
            self.assertEqual(action.player_id, player_id)
            self.assertEqual(action.action_type, "vote")

    def test_web_session_pure_ai_completes(self):
        with tempfile.TemporaryDirectory() as d:
            config = build_config(preset="6p", seed=505, human_players=[])
            session = WebGameSession(config=config, out_dir=d)
            session.start()
            deadline = time.time() + 5
            while not session.done and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(session.done)
            self.assertIsNone(session.error)
            self.assertTrue(session.log_path.exists())
            self.assertTrue(session.review_path.exists())
            self.assertTrue(session.html_path.exists())


    def test_openai_compatible_provider_against_local_mock_server(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length", "0"))
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
                body = json.dumps({
                    "choices": [{"message": {"content": "{\"action_type\":\"skip\",\"target_player_id\":null,\"content\":null,\"reasoning_summary\":\"mock\",\"confidence\":0.2}"}}]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A003
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenAICompatibleProvider(OpenAICompatibleConfig(
                api_key="test-key",
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model="mock-model",
                timeout=3,
                json_mode=True,
            ))
            raw = provider.generate("hello")
            self.assertIn('"action_type":"skip"', raw)
            self.assertEqual(captured["path"], "/v1/chat/completions")
            self.assertEqual(captured["auth"], "Bearer test-key")
            self.assertEqual(captured["body"]["model"], "mock-model")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
