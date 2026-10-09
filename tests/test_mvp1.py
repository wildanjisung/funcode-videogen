import tempfile
import unittest
from pathlib import Path

from videogen.application.ports import DependencyUnavailable, UserFacingError
from videogen.domain.models import MediaInfo, Word, build_cues, validate_words
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor
from videogen.infrastructure.fonts import SubtitleFont, default_font_path
from videogen.infrastructure.subtitles import SubtitleFiles


def media(width: int = 720, height: int = 1280) -> MediaInfo:
    return MediaInfo(0, 1, width, height, width, height, 10, 0, 0, "h264", "aac", "yuv420p", "bt709", "1:1")


class TimingTests(unittest.TestCase):
    def test_clip_only_after_negative_offset(self) -> None:
        words = validate_words([Word("ending", 11, 11.5)])
        cue = build_cues(words, 10, -2, 24)[0]
        self.assertEqual((cue.start, cue.end), (9, 9.5))
        self.assertEqual((cue.words[0].start, cue.words[0].end), (9, 9.5))
        self.assertEqual(words[0].start, 11)

    def test_positive_offset_and_video_edges(self) -> None:
        words = [Word("start", -2, 0), Word("end", 8, 9), Word("outside", 10, 11)]
        cues = build_cues(words, 10, 1.5, 24)
        self.assertEqual([(c.start, c.end) for c in cues], [(0, 1.5), (9.5, 10)])
        self.assertEqual([w.text for c in cues for w in c.words], ["start", "end"])

    def test_overlapping_sentence_boundary_keeps_full_intervals(self) -> None:
        cues = build_cues([Word("first.", 0, 2), Word("second", 1.5, 2.5)], 4, 0, 24)
        self.assertEqual(len(cues), 1)
        self.assertEqual([(w.start, w.end) for w in cues[0].words], [(0, 2), (1.5, 2.5)])

    def test_nested_word_end_does_not_shorten_cue(self) -> None:
        cue = build_cues([Word("long", 0, 2), Word("short", 1, 1.2)], 4, 0, 24)[0]
        self.assertEqual(cue.end, 2)
        self.assertEqual(cue.words[0].end, 2)

    def test_same_start_preserves_utterance_order_and_highlight_priority(self) -> None:
        cue = build_cues([Word("first", 0, 2), Word("second", 0, 1)], 4, 0, 24)[0]
        self.assertEqual(cue.text, "first second")
        events = SubtitleFiles._highlight_events(cue, 24)
        self.assertIn(r"{\1c&H00FFFF&}second{\1c&HFFFFFF&}", events[0][2])
        self.assertIn(r"{\1c&H00FFFF&}first{\1c&HFFFFFF&}", events[1][2])

    def test_invalid_times_and_normal_four_word_limit(self) -> None:
        self.assertEqual(validate_words([Word("bad", 0, float("inf"))]), [])
        cues = build_cues([Word(str(i), i * .2, i * .2 + .1) for i in range(9)], 4, 0, 24)
        self.assertEqual([len(c.words) for c in cues], [4, 4, 1])

    def test_active_colour_gaps_and_rounding(self) -> None:
        cue = build_cues([Word("win", 0, .5), Word("one", .7, 1.2), Word("job", 1.4, 2)], 4, 0, 24)[0]
        events = SubtitleFiles._highlight_events(cue, 24)
        self.assertEqual([(a, b) for a, b, _ in events], [(0, .5), (.5, .7), (.7, 1.2), (1.2, 1.4), (1.4, 2)])
        self.assertTrue(all("00FFFF" not in events[i][2] for i in (1, 3)))
        self.assertIn(r"{\1c&H00FFFF&}job{\1c&HFFFFFF&}", events[-1][2])
        tiny = build_cues([Word("tiny", .001, .002)], 4, 0, 24)[0]
        self.assertEqual(SubtitleFiles._highlight_events(tiny, 24), [])

    def test_font_selection_rejects_substitution_and_missing_evidence(self) -> None:
        renderer = FFmpegMediaProcessor(expected_font="HelveticaNeue-Bold")
        renderer._verify_font_selection("fontselect: (Helvetica Neue, 700, 0) -> HelveticaNeue-Bold, 0, HelveticaNeue-Bold")
        for log in ("", "fontselect: (Helvetica Neue, 700, 0) -> DejaVuSans, 0, DejaVuSans"):
            with self.assertRaises(UserFacingError):
                renderer._verify_font_selection(log)


class FontLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = default_font_path()
        if not path.is_file():
            raise unittest.SkipTest("Provide Helvetica Neue Bold through VIDEOGEN_FONT_PATH to check measured layout.")
        cls.font = SubtitleFont(path)
        cls.writer = SubtitleFiles(cls.font)

    def assert_layout_fits(self, cue, info) -> None:
        rows = [""]
        for _, separator, token in cue.layout:
            if separator == r"\N":
                rows.append(token)
            else:
                rows[-1] += separator + token
        self.assertLessEqual(len(rows), 2)
        border = max(1, round(cue.font_size * .025, 2))
        for row in rows:
            self.assertLessEqual(self.font.width(row, cue.font_size) + 2 * border, info.display_width * .84)

    def test_wide_word_portrait_and_landscape_preserves_text_timing(self) -> None:
        token = "W" * 35
        for info in (media(), media(1280, 720)):
            cue = self.writer.prepare_cues(info, build_cues([Word(token, 0, 1)], 10, 0, 24))[0]
            self.assert_layout_fits(cue, info)
            self.assertEqual("".join(text for _, _, text in cue.layout), token)
            self.assertEqual((cue.start, cue.end), (0, 1))
            self.assertGreaterEqual(cue.font_size, 18)
            for _, _, text in self.writer._highlight_events(cue, 24):
                self.assertEqual(text.count("00FFFF"), len(cue.layout))

    def test_segment_fallback_wraps_without_invented_word_timing(self) -> None:
        text = "entire segment with many words to wrap across two rows"
        cue = self.writer.prepare_cues(media(), build_cues([Word(text, 0, 3, False)], 10, 0, 24))[0]
        self.assert_layout_fits(cue, media())
        events = self.writer._highlight_events(cue, 24)
        self.assertEqual(len(events), 1)
        self.assertNotIn("00FFFF", events[0][2])
        self.assertEqual(events[0][:2], (0, 3))

    def test_measured_split_cannot_split_overlapping_words(self) -> None:
        words = [Word("W" * 12 + ".", 0, 2), Word("W" * 12, 1.5, 2.5), Word("next", 3, 4)]
        cues = self.writer.prepare_cues(media(), build_cues(words, 10, 0, 24))
        self.assertEqual([w.text for w in cues[0].words], [w.text for w in words[:2]])
        self.assertEqual(cues[0].end, 2.5)
        self.assertTrue(all(a.end <= b.start for a, b in zip(cues, cues[1:])))
        for cue in cues:
            self.assert_layout_fits(cue, media())

    def test_rejects_missing_corrupt_wrong_family_and_regular_font(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.otf"
            with self.assertRaises(DependencyUnavailable):
                SubtitleFont(invalid)
            invalid.write_bytes(b"not a font")
            with self.assertRaises(DependencyUnavailable):
                SubtitleFont(invalid)
        wrong = Path(__file__).parents[1] / "src/videogen/presentation/resources/DejaVuSans.ttf"
        with self.assertRaises(DependencyUnavailable):
            SubtitleFont(wrong)
        regular = default_font_path().with_name("HelveticaNeueRoman.otf")
        if regular.is_file():
            with self.assertRaises(DependencyUnavailable):
                SubtitleFont(regular)

    def test_impossible_segment_fails_instead_of_cropping(self) -> None:
        words = [Word("W" * 1000, 0, 3, False)]
        with self.assertRaises(UserFacingError):
            self.writer.prepare_cues(media(), build_cues(words, 10, 0, 24))


if __name__ == "__main__":
    unittest.main()
