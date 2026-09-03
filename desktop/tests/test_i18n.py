"""Tests for locale detection and string lookup.

Both languages must define the same keys — a key present in only one of them
shows up as raw "log_listening" text in that locale's UI.
"""

import unittest

from openmic import i18n


class TestLanguageDetection(unittest.TestCase):
    def test_explicit_override_wins(self):
        env = {"OPENMIC_LANG": "pt", "LANG": "en_US.UTF-8"}
        self.assertEqual(i18n.detect_language(env), "pt")

    def test_locale_variants_are_normalized(self):
        self.assertEqual(i18n.detect_language({"LANG": "pt_BR.UTF-8"}), "pt")
        self.assertEqual(i18n.detect_language({"LANG": "en-GB"}), "en")

    def test_unsupported_locale_falls_back_to_default(self):
        self.assertEqual(i18n.detect_language({"LANG": "ja_JP.UTF-8"}), i18n.DEFAULT_LANGUAGE)
        self.assertEqual(i18n.detect_language({}), i18n.DEFAULT_LANGUAGE)

    def test_empty_locale_value_is_skipped(self):
        self.assertEqual(i18n.detect_language({"LC_ALL": "", "LANG": "pt_BR"}), "pt")


class TestTranslation(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.get_language())

    def test_translates_and_interpolates(self):
        i18n.set_language("pt")
        self.assertEqual(i18n.tr("port"), "Porta:")
        self.assertIn("192.168.0.10", i18n.tr("use_this_address", ip="192.168.0.10"))

    def test_unknown_key_returns_the_key(self):
        self.assertEqual(i18n.tr("no_such_string"), "no_such_string")

    def test_missing_placeholder_does_not_raise(self):
        self.assertIsInstance(i18n.tr("use_this_address"), str)

    def test_unsupported_language_falls_back(self):
        i18n.set_language("ja")
        self.assertEqual(i18n.get_language(), i18n.DEFAULT_LANGUAGE)

    def test_every_language_defines_the_same_keys(self):
        reference = set(i18n._STRINGS[i18n.DEFAULT_LANGUAGE])
        for language in i18n.SUPPORTED_LANGUAGES:
            self.assertEqual(set(i18n._STRINGS[language]), reference, language)


if __name__ == "__main__":
    unittest.main()
