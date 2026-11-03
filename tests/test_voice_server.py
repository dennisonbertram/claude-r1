import importlib.machinery
import json
import tempfile
import importlib.util
import os
import threading
import time
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "termux", "bin", "voice-server")


def load():
    loader = importlib.machinery.SourceFileLoader("vs", PATH)
    spec = importlib.util.spec_from_loader("vs", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


vs = load()


class FakeClaude:
    def __init__(self):
        self.seen = []

    def cold(self):
        return False

    def ask(self, content, on_tool=None):
        self.seen.append(content)
        return "ok"


class FakeSpeaker:
    def claim(self):
        return 0

    def say(self, text, token=None):
        pass

    def speaking(self):
        return False

    def stop(self):
        pass


class ReplyRulesTest(unittest.TestCase):
    def agent(self):
        a = object.__new__(vs.Agent)
        a.turn = 1
        a.lock = threading.Lock()
        a.before = None
        a.parked = None
        a.claude = FakeClaude()
        a.speaker = FakeSpeaker()
        return a

    def test_rules_appended_to_text_turn_but_not_shown(self):
        a = self.agent()
        a._respond(1, "weather in brooklyn", "weather in brooklyn", "")
        sent = a.claude.seen[0]
        self.assertTrue(sent.endswith(vs.REPLY_RULES))
        self.assertEqual(vs.HUB.state["you"], "weather in brooklyn")
        for v in vs.HUB.state.values():
            self.assertNotIn("Reply rules", str(v))
        self.assertEqual(a.last_content, ("weather in brooklyn", "weather in brooklyn", ""))

    def test_retry_adds_rules_once(self):
        a = self.agent()
        a._respond(1, "stock", "stock", "")
        vs.HUB.set(state="answer")
        a.retry()
        self.assertEqual(a.claude.seen[1].count("Reply rules"), 1)

    def test_photo_content_unchanged(self):
        photo = [{"type": "image"}]
        self.assertIs(vs.with_rules(photo), photo)

    def test_system_prompt(self):
        self.assertIn("Never end with warnings, caveats or advice to check again or double-check; "
                      "give the answer and stop. ", vs.SYSTEM)
        self.assertIn("If you can't find live data, say so in one short sentence", vs.SYSTEM)
        self.assertIn("Holding a finger on the screen opens a menu", vs.SYSTEM)


class FakeResp:
    def __init__(self):
        self.closed = False
        self.sent = False

    def read(self, n=-1):
        if self.sent:
            return b""
        self.sent = True
        return b"\0" * 16

    def close(self):
        self.closed = True


class FakePopen:
    calls = []

    def __init__(self, argv, **kw):
        FakePopen.calls.append(argv)
        self.pid = 1
        self.stdin = mock.Mock()

    def poll(self):
        return 0

    def wait(self):
        return 0

    def kill(self):
        pass


class BlockingUrlopen:
    def __init__(self):
        self.entered, self.release, self.resp = threading.Event(), threading.Event(), FakeResp()

    def __call__(self, req, timeout=None):
        self.entered.set()
        self.release.wait(5)
        return self.resp


def patched(urlopen):
    FakePopen.calls = []
    return [mock.patch.object(vs.urllib.request, "urlopen", urlopen),
            mock.patch.object(vs.subprocess, "Popen", FakePopen),
            mock.patch.object(vs, "el_key", lambda: "k"),
            mock.patch.object(vs.os, "killpg", lambda *a: None)]


class SpeakerRaceTest(unittest.TestCase):
    def setUp(self):
        self.ps = patched(BlockingUrlopen())
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()

    def test_stop_during_connect_prevents_player(self):
        uo = vs.urllib.request.urlopen
        sp = vs.Speaker()
        tok = sp.claim()
        t = threading.Thread(target=sp.say, args=("hi", tok))
        t.start()
        self.assertTrue(uo.entered.wait(2))
        self.assertTrue(sp.speaking())
        sp.stop()
        self.assertFalse(sp.speaking())
        uo.release.set()
        t.join(3)
        self.assertEqual(FakePopen.calls, [])
        self.assertTrue(uo.resp.closed)

    def test_urlerror_falls_back_to_espeak(self):
        def boom(req, timeout=None):
            raise urllib.error.URLError("offline")
        with mock.patch.object(vs.urllib.request, "urlopen", boom):
            vs.Speaker().say("hello")
        self.assertEqual(len(FakePopen.calls), 1)
        self.assertEqual(FakePopen.calls[0][0], "bash")
        self.assertIn("espeak", FakePopen.calls[0][2])

    def test_stale_token_skips_espeak_too(self):
        def boom(req, timeout=None):
            sp.stop()
            raise urllib.error.URLError("offline")
        sp = vs.Speaker()
        with mock.patch.object(vs.urllib.request, "urlopen", boom):
            sp.say("hello")
        self.assertEqual(FakePopen.calls, [])


class BigClaude(FakeClaude):
    def ask(self, content, on_tool=None):
        return "Tokyo is big."


class FakeRec:
    def __init__(self):
        self.started = self.stopped = 0
        self.on = False

    def start(self):
        self.started += 1
        self.on = True

    def recording(self):
        return self.on

    def stop(self):
        self.stopped += 1
        self.on = False
        return 0.0

    def spoke(self):
        return False


def make_agent(claude=None, speaker=None):
    a = object.__new__(vs.Agent)
    a.turn, a.rec_id, a.ptt = 1, 0, None
    a.lock = threading.Lock()
    a.before = a.parked = a.saved = a.last_content = None
    a.claude = claude or FakeClaude()
    a.speaker = speaker or FakeSpeaker()
    a.rec = FakeRec()
    return a


class AgentRaceTest(unittest.TestCase):
    def test_tap_between_speaking_and_player_stops_speech(self):
        uo = BlockingUrlopen()
        ps = patched(uo)
        for p in ps:
            p.start()
        try:
            a = make_agent(BigClaude(), vs.Speaker())
            t = threading.Thread(target=a._respond, args=(1, "q", "q", ""))
            t.start()
            self.assertTrue(uo.entered.wait(2))
            self.assertEqual(vs.HUB.state["state"], "speaking")
            a.talk()
            self.assertEqual(vs.HUB.state["state"], "listening")
            self.assertEqual(a.saved["state"], "answer")
            uo.release.set()
            t.join(3)
            self.assertEqual(FakePopen.calls, [])
        finally:
            for p in ps:
                p.stop()


class OfflineGateTest(unittest.TestCase):
    def agent(self, state="answer", online=False):
        a = make_agent()
        vs.HUB.set(state=state, online=online, notice="", retry=False, you="q", reply="r", error="")
        return a

    def test_tap_offline_refuses_without_recording(self):
        a = self.agent()
        with mock.patch.object(vs, "online", lambda: False):
            a.talk()
        self.assertEqual(vs.HUB.state["state"], "answer")
        self.assertEqual(vs.HUB.state["notice"], vs.OFFLINE_NOTICE)
        self.assertEqual(a.rec.started, 0)

    def test_tap_offline_rechecks_and_proceeds(self):
        a = self.agent()
        with mock.patch.object(vs, "online", lambda: True):
            a.talk()
        self.assertEqual(vs.HUB.state["state"], "listening")
        self.assertTrue(vs.HUB.state["online"])

    def test_retry_offline_does_not_start_turn(self):
        a = self.agent()
        a.last_content = ("q", "q", "")
        vs.HUB.set(retry=True)
        with mock.patch.object(vs, "online", lambda: False):
            a.retry()
        self.assertEqual(a.claude.seen, [])
        self.assertEqual(a.turn, 1)
        self.assertTrue(vs.HUB.state["retry"])
        self.assertEqual(vs.HUB.state["notice"], vs.OFFLINE_NOTICE)

    def test_hold_offline_keeps_pending(self):
        a = self.agent()
        said = []
        a.speaker.say = lambda text, token=None: said.append(text)
        with mock.patch.object(vs, "online", lambda: False):
            a.ptt_press()
            a.ptt_hold()
            time.sleep(0.2)
        self.assertEqual(a.ptt, "pending")
        self.assertNotEqual(vs.HUB.state["state"], "listening")
        self.assertEqual(vs.HUB.state["notice"], vs.OFFLINE_NOTICE)
        self.assertEqual(said, ["No internet connection."])
        a.ptt_release()
        self.assertEqual(a.rec.stopped, 1)

    def test_tap_while_speaking_not_gated_offline(self):
        a = self.agent(state="speaking")
        with mock.patch.object(vs, "online", lambda: False):
            a.talk()
        self.assertEqual(vs.HUB.state["state"], "listening")


if __name__ == "__main__":
    unittest.main()


class StartOverHelpTest(unittest.TestCase):
    """Questions about starting over get fixed help text instead of a model answer."""

    def test_matches_only_app_questions(self):
        vs = load()
        yes = ["How do I start over?", "Can I start a new conversation?", "how to reset", "Let's start over.",
               "Can you forget this conversation?"]
        no = ["What does reset mean in tennis?", "How do I clear the dishwasher filter?", "How do I reset my router?"]
        for t in yes:
            self.assertTrue(vs.HOW_START_OVER.search(t), t)
        for t in no:
            self.assertFalse(vs.HOW_START_OVER.search(t), t)
        self.assertIn("Start over", vs.START_OVER_HELP)


class MemoryAndContextTest(unittest.TestCase):
    def test_system_prompt_includes_remembered_facts(self):
        with tempfile.TemporaryDirectory() as d:
            vs.MEMORY_FILE = os.path.join(d, "memory.json")
            self.assertEqual(vs.system_prompt().count("WHAT YOU KNOW"), 0)
            json.dump([{"id": 1, "fact": "Dennison likes jazz", "added": "2026-11-03"}], open(vs.MEMORY_FILE, "w"))
            self.assertIn("- Dennison likes jazz", vs.system_prompt())

    def test_text_turns_carry_date_time_and_location(self):
        sent = vs.with_rules("what's on tonight?")
        self.assertTrue(sent.startswith("[Now: "), sent)
        self.assertIn("location:", sent.split("\n")[0])
        self.assertIn("what's on tonight?", sent)
