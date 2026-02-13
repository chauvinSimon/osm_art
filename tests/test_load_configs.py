import unittest

from utils.utils import load_config


class TestLoadConfigs(unittest.TestCase):
    def test_load_project_config(self):

        config = load_config()
        self.assertIsNotNone(config["projects"])


if __name__ == "__main__":
    unittest.main()
