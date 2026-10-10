"""Non-destructive source intervals and a single output-time mapping."""
from dataclasses import asdict, dataclass, replace
from bisect import bisect_left
import math
from uuid import uuid4

from videogen.domain.models import Word, build_cues, max_line_characters


@dataclass(frozen=True)
class Segment:
    id: str
    start: float
    end: float


@dataclass(frozen=True)
class MappedWord(Word):
    source_id: str = ""
    segment_id: str = ""
    partial: bool = False


@dataclass(frozen=True)
class TimelineEdit:
    segments: tuple[Segment, ...]
    source_duration: float

    @classmethod
    def from_dict(cls, value, duration):
        if value is None:
            return cls((Segment("source", 0.0, duration),), duration)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Versi timeline tidak didukung.")
        segments = tuple(Segment(**item) for item in value.get("segments", []))
        previous, identities = 0.0, set()
        for item in segments:
            if (not isinstance(item.id, str) or not item.id or item.id in identities
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (item.start, item.end))
                    or item.start < previous - 1e-9 or item.start < 0 or item.end > duration + 1e-9 or item.end <= item.start):
                raise ValueError("Segmen timeline tidak valid atau bertumpang tindih.")
            previous = item.end
            identities.add(item.id)
        return cls(segments, duration)

    def to_dict(self):
        return {"schema_version": 1, "segments": [asdict(item) for item in self.segments]}

    @property
    def duration(self):
        return sum(item.end - item.start for item in self.segments)

    def source_time(self, output_time):
        cursor = 0.0
        for item in self.segments:
            length = item.end - item.start
            if cursor <= output_time < cursor + length:
                return item.start + output_time - cursor
            cursor += length
        raise ValueError("Waktu berada di luar hasil edit.")

    def split(self, output_time):
        cursor = 0.0
        for index, item in enumerate(self.segments):
            length = item.end - item.start
            if cursor < output_time < cursor + length:
                cut = item.start + output_time - cursor
                return replace(self, segments=(*self.segments[:index], replace(item, end=cut),
                    Segment(uuid4().hex[:12], cut, item.end), *self.segments[index+1:]))
            cursor += length
        raise ValueError("Split harus berada di dalam segmen.")

    def map_words(self, words, offset):
        # Coalesce adjacent splits so splitting alone cannot duplicate a word/cue.
        runs = []
        for segment in self.segments:
            if runs and abs(runs[-1].end - segment.start) < 1e-9:
                runs[-1] = replace(runs[-1], end=segment.end)
            else:
                runs.append(segment)
        result, cursor = [], 0.0
        for run in runs:
            for index, word in enumerate(words):
                start, end = word.start + offset, word.end + offset
                left, right = max(start, run.start), min(end, run.end)
                if right > left:
                    result.append(MappedWord(word.text, cursor + left - run.start, cursor + right - run.start,
                        word.has_word_timing, str(index), run.id, left > start + 1e-9 or right < end - 1e-9))
            cursor += run.end - run.start
        return result


def project_cues(words, info):
    """Shared grouping policy for editor, playback and export; break at cuts."""
    groups = []
    for word in words:
        key = getattr(word, "segment_id", "source")
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(word)
    return [cue for _, group in groups for cue in build_cues(group, info.duration, 0,
        min(24, max_line_characters(info)))]


def edited_transcript(words):
    seen, tokens = set(), []
    for word in words:
        identity = getattr(word, "source_id", None)
        if identity is None or identity not in seen:
            tokens.append(word.text.strip())
            seen.add(identity)
    return " ".join(tokens)


def nearest_boundary(seconds, boundaries):
    if not boundaries:
        raise ValueError("Timestamp frame sumber belum tersedia.")
    index = bisect_left(boundaries, seconds)
    choices = boundaries[max(0, index-1):min(len(boundaries), index+1)]
    return min(choices, key=lambda value: (round(abs(value-seconds), 12), value))
