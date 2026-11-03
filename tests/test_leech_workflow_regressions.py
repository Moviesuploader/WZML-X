from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LeechWorkflowRegressionTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text()

    def test_qbl_cleanup_preserves_replied_torrent_message(self):
        helper = self.read("bot/helper/telegram_helper/message_utils.py")
        mirror = self.read("bot/modules/mirror_leech.py")
        listener = self.read("bot/helper/listeners/task_listener.py")
        self.assertIn("def delete_links(message, keep_reply=False)", helper)
        self.assertIn("keep_reply=self.is_qbit", mirror)
        self.assertIn("keep_reply=self.is_qbit", listener)

    def test_extracted_files_upload_sequentially(self):
        source = self.read("bot/helper/mirror_leech_utils/upload_utils/telegram_uploader.py")
        self.assertIn("or self._listener.extract", source)
        self.assertIn("natsorted(files)", source)

    def test_settings_countdown_cleans_up_handler(self):
        source = self.read("bot/modules/users_settings.py")
        self.assertIn("finally:", source)
        self.assertIn("client.remove_handler(*handler)", source)


if __name__ == "__main__":
    unittest.main()
