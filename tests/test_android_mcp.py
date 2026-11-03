import os, tempfile, unittest, unittest.mock
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


class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL for the email tools."""
    MSGS = {b"1": (b"\\Seen", b"From: Ann <ann@example.com>\r\nSubject: Lunch\r\nDate: Mon, 2 Nov 2026 12:00:00 -0500\r\n\r\nNoon at Lucali?\r\n"),
            b"2": (b"", b"From: Bank <no-reply@bank.example>\r\nSubject: Statement ready\r\nDate: Tue, 3 Nov 2026 09:00:00 -0500\r\n\r\nYour statement is ready.\r\n")}
    appended = []

    def __init__(self, host, port, timeout=None):
        self.host = host
    def login(self, user, password): return "OK", [b"logged in"]
    def logout(self): pass
    def select(self, box, readonly=False):
        self.readonly = readonly
        return "OK", [b"2"]
    def search(self, charset, *criteria):
        if criteria[0] == "UNSEEN":
            return "OK", [b"2"]
        if criteria[0] == "TEXT":
            word = criteria[1].strip('"').lower()
            return "OK", [b" ".join(i for i, (_, raw) in self.MSGS.items() if word in raw.decode().lower())]
        return "OK", [b"1 2"]
    def fetch(self, i, what):
        i = i if isinstance(i, bytes) else i.encode()
        flags, raw = self.MSGS[i]
        return "OK", [(b"%s (FLAGS (%s) BODY[])" % (i, flags), raw), b")"]
    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"', b'(\\HasNoChildren) "/" "INBOX"']
    def append(self, box, flags, when, msg):
        FakeIMAP.appended.append((box, msg))
        return "OK", [b"appended"]


class EmailToolsTest(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.dir = tempfile.TemporaryDirectory()
        self.m.EMAIL_FILE = os.path.join(self.dir.name, "email.json")
        with open(self.m.EMAIL_FILE, "w") as f:
            f.write('{"address": "me@gmail.com", "password": "app-password"}')
        import imaplib
        self.patch = unittest.mock.patch.object(imaplib, "IMAP4_SSL", FakeIMAP)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def test_inbox_newest_first_with_unread_marker(self):
        out = self.m.t_email_inbox({})[0][0]["text"].splitlines()
        self.assertTrue(out[0].startswith("#2 [unread]") and "Statement ready" in out[0], out)
        self.assertIn("Ann <ann@example.com> | Lunch", out[1])

    def test_read_and_search(self):
        self.assertIn("Noon at Lucali?", self.m.t_email_read({"id": "#1"})[0][0]["text"])
        self.assertIn("Statement ready", self.m.t_email_search({"query": "statement"})[0][0]["text"])

    def test_draft_goes_to_the_drafts_folder(self):
        text, err = self.m.t_email_draft({"to": "ann@example.com", "subject": "Re: Lunch", "body": "See you there"})
        self.assertFalse(err)
        box, msg = FakeIMAP.appended[-1]
        self.assertEqual(box, '"[Gmail]/Drafts"')
        self.assertIn(b"See you there", msg)

    def test_no_account_explains_setup(self):
        os.remove(self.m.EMAIL_FILE)
        with self.assertRaisesRegex(RuntimeError, "No email account"):
            self.m.t_email_inbox({})
