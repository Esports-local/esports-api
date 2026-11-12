"""roi_ocr 결과(runs)를 화면 정보로 정리한다."""

STATIC_TAGS = ("team", "player_name", "standing")  # 경기 내내 같은 값
SNAPSHOT_TAGS = ("game_time", "team", "team_kills", "player_name", "kda")


def filter_runs(runs: list[dict], tags: set[str] | None = None, min_samples: int = 2) -> list[dict]:
    """tag 와 샘플 수로 거른다 (min_samples 미만은 화면 전환 순간의 잡음)."""
    return [r for r in runs if r["samples"] >= min_samples and (not tags or r["tag"] in tags)]


def static_values(runs: list[dict]) -> dict[str, dict[str, str]]:
    """팀·선수 이름처럼 안 바뀌는 값: 영역마다 화면에 가장 오래 떠 있던 값."""
    dur: dict[tuple, float] = {}
    for r in runs:
        if r["tag"] in STATIC_TAGS:
            key = (r["tag"], r["slot"] or "value", r["text"])
            dur[key] = dur.get(key, 0) + r["end_sec"] - r["start_sec"]
    best: dict[tuple, tuple[str, float]] = {}
    for (tag, slot, text), d in dur.items():
        if d > best.get((tag, slot), ("", -1.0))[1]:
            best[(tag, slot)] = (text, d)
    out: dict[str, dict[str, str]] = {}
    for (tag, slot), (text, _) in best.items():
        out.setdefault(tag, {})[slot] = text
    return out


def snapshot(runs: list[dict], t: float, statics: dict | None = None) -> dict:
    """t 초에 화면에 떠 있던 값 {tag: {slot: text}}. 안 바뀌는 값은 statics 로 채운다."""
    snap: dict[str, dict[str, str]] = {}
    for r in runs:
        if r["tag"] in SNAPSHOT_TAGS and r["tag"] not in STATIC_TAGS and r["samples"] >= 2 \
                and r["start_sec"] <= t < r["end_sec"]:
            snap.setdefault(r["tag"], {})[r["slot"] or "value"] = r["text"]
    for tag, values in (statics or {}).items():
        if tag in SNAPSHOT_TAGS:
            snap[tag] = dict(values)
    out = {k: snap[k] for k in SNAPSHOT_TAGS if k in snap}
    if "game_time" in out:
        out["game_time"] = out["game_time"].get("value")
    return out
