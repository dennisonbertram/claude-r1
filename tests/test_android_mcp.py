import os, tempfile, unittest
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader, module_from_spec

SRC = os.path.join(os.path.dirname(__file__), "..", "termux", "bin", "android-mcp")


def load():
    # importing creates ~/.config/r1/mcp_token, so point HOME at a temp dir
    old, tmp = os.environ.get("HOME"), tempfile.mkdtemp()
    os.environ["HOME"] = tmp
    try:
        loader = SourceFileLoader("android_mcp", SRC)
        mod = module_from_spec(spec_from_loader("android_mcp", loader))
        loader.exec_module(mod)
        return mod
    finally:
        if old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old


class ShowCardDescription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load()
        cls.desc = cls.mod.BY_NAME["show_card"][1]

    def test_starts_with_always(self):
        self.assertTrue(self.desc.startswith("ALWAYS call this before your reply when the answer has glanceable data: "))

    def test_field_limits(self):
        self.assertIn("1-2 words", self.desc)
        self.assertIn("max 20 characters", self.desc)
        self.assertIn("under 30 characters", self.desc)

    def test_schema_unchanged(self):
        self.assertIn("html", self.mod.CARD_TYPES)


if __name__ == "__main__":
    unittest.main()


class MemoryToolsTest(unittest.TestCase):
    def test_remember_recall_forget(self):
        m = load()
        with tempfile.TemporaryDirectory() as d:
            m.MEMORY_FILE = os.path.join(d, "memory.json")
            m.t_remember({"fact": "Dennison lives in  Brooklyn"})
            m.t_remember({"fact": "Dennison likes jazz"})
            self.assertEqual(m.t_remember({"fact": "dennison likes jazz"})[0][0]["text"], "Already remembered.")
            text = m.t_recall({})[0][0]["text"]
            self.assertIn("1. Dennison lives in Brooklyn", text)
            self.assertIn("2. Dennison likes jazz", text)
            m.t_forget({"fact": "jazz"})
            self.assertNotIn("jazz", m.t_recall({})[0][0]["text"])
            self.assertTrue(m.t_forget({"fact": "nothing like this"})[1])
