"""
Shared clip-building logic for all the step-5 selectors.

THE PROBLEM THIS SOLVES
-----------------------
The first version padded every chosen segment by a fixed number of seconds
(PAD = 1.2) so clips wouldn't start mid-sentence. But a blind time pad bleeds
into whatever the *neighbouring* sentence is saying, so clips routinely began or
ended in the middle of a word.

THE FIX
-------
Never cut inside a transcript segment. Whisper already tells us exactly where
every utterance starts and ends, and it breaks segments at natural pauses — so
those boundaries are good cut points. Instead of "add 1.2 seconds", we expand
each clip *outward to the nearest segment boundary*. Cuts then always land in
the pause between utterances.

Used by select_highlights.py, select_extractive.py, select_llm.py and
make_reel.py so all of them cut identically.
"""

EPS = 1e-6


def segment_bounds(segments):
    """Sorted lists of every segment start and end time."""
    return (sorted(s["start"] for s in segments),
            sorted(s["end"] for s in segments))


def snap_range(start, end, segments):
    """Expand [start, end] outward to the nearest transcript boundaries.

    Outward, never inward — so we can only ever include more of an utterance,
    never slice one in half.
    """
    if not segments:
        return start, end
    starts, ends = segment_bounds(segments)

    before = [x for x in starts if x <= start + EPS]
    snapped_start = max(before) if before else min(starts)

    after = [x for x in ends if x >= end - EPS]
    snapped_end = min(after) if after else max(ends)

    if snapped_end <= snapped_start:            # degenerate guard
        snapped_end = max(snapped_start, end)
    return snapped_start, snapped_end


def with_context(index, segments, context):
    """Range covering segment `index` plus `context` neighbours either side.

    context=0 -> just that sentence. context=1 -> one sentence of lead-in and
    lead-out, which usually makes a clip feel less abrupt.
    """
    lo = max(0, index - context)
    hi = min(len(segments) - 1, index + context)
    return segments[lo]["start"], segments[hi]["end"]


def text_for_range(segments, start, end):
    """Join the text of every segment overlapping [start, end]."""
    parts = [s.get("text", "").strip() for s in segments
             if s["end"] > start + EPS and s["start"] < end - EPS]
    return " ".join(p for p in parts if p)


def merge_and_cap(windows, merge_gap, max_total):
    """Merge near-adjacent windows, then trim to a total duration budget."""
    if not windows:
        return []
    windows = sorted(windows, key=lambda w: w["start"])

    merged = [dict(windows[0])]
    for w in windows[1:]:
        last = merged[-1]
        if w["start"] <= last["end"] + merge_gap:
            last["end"] = max(last["end"], w["end"])
        else:
            merged.append(dict(w))

    if max_total:
        total, capped = 0.0, []
        for w in merged:
            dur = w["end"] - w["start"]
            if total + dur > max_total:
                break
            capped.append(w)
            total += dur
        merged = capped or merged[:1]
    return merged


def build_clips(picks, segments, context=0, merge_gap=2.5, max_total=50):
    """Turn chosen SEGMENTS into snapped, merged, capped clips.

    `picks` are segment dicts taken from `segments` (what the keyword and
    TextRank selectors produce).
    """
    if not picks:
        return []
    # locate each pick in the transcript so we can pull in its neighbours
    index_of = {(round(s["start"], 3), round(s["end"], 3)): i
                for i, s in enumerate(segments)}

    windows = []
    for p in picks:
        key = (round(p["start"], 3), round(p["end"], 3))
        i = index_of.get(key)
        if i is None:
            start, end = p["start"], p["end"]
        else:
            start, end = with_context(i, segments, context)
        start, end = snap_range(start, end, segments)
        windows.append({"start": start, "end": end})

    merged = merge_and_cap(windows, merge_gap, max_total)
    return [{"start": round(w["start"], 2), "end": round(w["end"], 2),
             "text": text_for_range(segments, w["start"], w["end"])}
            for w in merged]


def build_clips_from_ranges(ranges, segments, merge_gap=1.5, max_total=50):
    """Turn arbitrary TIME RANGES into snapped, merged, capped clips.

    Used for the LLM selector, which returns its own start/end times. Snapping
    them makes the result deterministic instead of trusting the model to land
    on sensible boundaries.
    """
    if not segments:
        return []
    lo = min(s["start"] for s in segments)
    hi = max(s["end"] for s in segments)

    windows = []
    for start, end in ranges:
        start = max(lo, min(float(start), hi))
        end = max(lo, min(float(end), hi))
        if end - start <= 0.3:                  # ignore degenerate ranges
            continue
        start, end = snap_range(start, end, segments)
        windows.append({"start": start, "end": end})

    merged = merge_and_cap(windows, merge_gap, max_total)
    return [{"start": round(w["start"], 2), "end": round(w["end"], 2),
             "text": text_for_range(segments, w["start"], w["end"])}
            for w in merged]
