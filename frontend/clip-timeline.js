/**
 * ClipTimeline — stacked video scrubber with clip in/out selection.
 * Main track: playback progress. Clip range sits directly on top (lavender band only).
 */
class ClipTimeline {
  constructor(root, { video, onRangeChange, onSeek } = {}) {
    this.root = root;
    this.video = video;
    this.onRangeChange = onRangeChange || (() => {});
    this.onSeek = onSeek || (() => {});
    this.start = 0;
    this.end = 15;
    this.duration = 0;
    this.minGap = 1;
    this._drag = null;

    this._els = {
      current: root.querySelector("[data-tl-current]"),
      total: root.querySelector("[data-tl-total]"),
      clipMeta: root.querySelector("[data-tl-clip-meta]"),
      stack: root.querySelector("[data-tl-stack]"),
      mainTrack: root.querySelector('[data-track="main"]'),
      clipTrack: root.querySelector('[data-track="clip"]'),
      played: root.querySelector("[data-tl-played]"),
      playhead: root.querySelector("[data-tl-playhead]"),
      range: root.querySelector("[data-tl-range]"),
      rangeFill: root.querySelector("[data-tl-range-fill]"),
      handleStart: root.querySelector('[data-handle="start"]'),
      handleEnd: root.querySelector('[data-handle="end"]'),
      startInput: root.querySelector("[data-tl-start-input]"),
      endInput: root.querySelector("[data-tl-end-input]"),
      setStartBtn: root.querySelector("[data-tl-set-start]"),
      setEndBtn: root.querySelector("[data-tl-set-end]"),
      previewBtn: root.querySelector("[data-tl-preview]"),
      playBtn: root.querySelector("[data-tl-play]"),
    };

    this._bind();
    this.render();
  }

  setDuration(duration) {
    const value = Number(duration);
    if (!Number.isFinite(value) || value <= 0) return;
    this.duration = value;
    if (this.end > this.duration) this.end = this.duration;
    if (this.start >= this.end) this.start = Math.max(0, this.end - this.minGap);
    this.render();
  }

  setRange(start, end, { silent = false } = {}) {
    const max = this.duration || Math.max(end, start + this.minGap);
    this.start = this._clamp(start, 0, max - this.minGap);
    this.end = this._clamp(end, this.start + this.minGap, max);
    this.render();
    if (!silent) this.onRangeChange(this.start, this.end);
  }

  setPlayhead(time) {
    this._renderPlayhead(time);
  }

  render() {
    const duration = this.duration || Math.max(this.end, 1);
    const startPct = (this.start / duration) * 100;
    const endPct = (this.end / duration) * 100;
    const clipSeconds = Math.max(0, this.end - this.start);

    if (this._els.current) this._els.current.textContent = ClipTimeline.formatTime(this.video?.currentTime || 0);
    if (this._els.total) this._els.total.textContent = ClipTimeline.formatTime(duration);
    if (this._els.clipMeta) {
      this._els.clipMeta.textContent = `${ClipTimeline.formatTime(this.start)} – ${ClipTimeline.formatTime(this.end)} · ${Math.round(clipSeconds)}s`;
    }
    if (this._els.startInput) this._els.startInput.value = ClipTimeline.formatTime(this.start);
    if (this._els.endInput) this._els.endInput.value = ClipTimeline.formatTime(this.end);

    if (this._els.range) {
      this._els.range.style.left = `${startPct}%`;
      this._els.range.style.width = `${Math.max(endPct - startPct, 0)}%`;
    }

    this._renderPlayhead(this.video?.currentTime || 0);
  }

  _renderPlayhead(time) {
    const duration = this.duration || Math.max(this.end, 1);
    const pct = this._clamp((time / duration) * 100, 0, 100);
    if (this._els.played) this._els.played.style.width = `${pct}%`;
    if (this._els.playhead) this._els.playhead.style.left = `${pct}%`;
    if (this._els.current) this._els.current.textContent = ClipTimeline.formatTime(time);
  }

  _bind() {
    this._els.setStartBtn?.addEventListener("click", () => {
      if (!this.video) return;
      this.setRange(this.video.currentTime || 0, Math.max(this.end, (this.video.currentTime || 0) + this.minGap));
    });

    this._els.setEndBtn?.addEventListener("click", () => {
      if (!this.video) return;
      this.setRange(this.start, Math.max((this.video.currentTime || 0), this.start + this.minGap));
    });

    this._els.previewBtn?.addEventListener("click", () => this._previewRange());

    this._els.playBtn?.addEventListener("click", () => this._togglePlay());

    this.video?.addEventListener("play", () => this._syncPlayButton(true));
    this.video?.addEventListener("pause", () => this._syncPlayButton(false));

    this._els.startInput?.addEventListener("change", () => {
      const start = ClipTimeline.parseTime(this._els.startInput.value);
      this.setRange(start, Math.max(this.end, start + this.minGap));
    });

    this._els.endInput?.addEventListener("change", () => {
      const end = ClipTimeline.parseTime(this._els.endInput.value);
      this.setRange(this.start, Math.max(end, this.start + this.minGap));
    });

    this._els.stack?.addEventListener("pointerdown", (event) => {
      if (event.target.closest("[data-tl-range-fill]") || event.target.closest("[data-handle]")) return;
      if (event.target.closest("[data-tl-range]")) {
        this._onTrackPointerDown(event, "clip");
        return;
      }
      this._onTrackPointerDown(event, "main");
    });

    this._els.handleStart?.addEventListener("pointerdown", (event) => this._onHandlePointerDown(event, "start"));
    this._els.handleEnd?.addEventListener("pointerdown", (event) => this._onHandlePointerDown(event, "end"));
    this._els.rangeFill?.addEventListener("pointerdown", (event) => this._onRangeBodyPointerDown(event));

    this.video?.addEventListener("timeupdate", () => this._renderPlayhead(this.video.currentTime || 0));
    this.video?.addEventListener("loadedmetadata", () => this.setDuration(this.video.duration));
  }

  _previewRange() {
    if (!this.video) return;
    this._stopPreview();

    const video = this.video;
    const stopAt = this.end;

    const onTime = () => {
      if (video.currentTime >= stopAt) {
        video.pause();
        this._stopPreview();
      }
    };

    const startPlayback = () => {
      ClipTimeline._safePlay(video);
      video.addEventListener("timeupdate", onTime);
    };

    const onSeeked = () => {
      video.removeEventListener("seeked", onSeeked);
      startPlayback();
    };

    this._previewStop = () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("seeked", onSeeked);
      this._previewStop = null;
    };

    video.pause();
    video.addEventListener("seeked", onSeeked);
    video.currentTime = this.start;
    if (!video.seeking) onSeeked();
  }

  _stopPreview() {
    if (this._previewStop) this._previewStop();
  }

  _togglePlay() {
    if (!this.video) return;
    if (this.video.paused) ClipTimeline._safePlay(this.video);
    else {
      this._stopPreview();
      this.video.pause();
    }
  }

  _syncPlayButton(isPlaying) {
    if (!this._els.playBtn) return;
    this._els.playBtn.textContent = isPlaying ? "Pause" : "Play";
  }

  _onTrackPointerDown(event, track) {
    if (!this.duration) return;
    event.preventDefault();
    const captureEl = this._els.stack || this._els.mainTrack;
    const time = this._timeFromClientX(event.clientX);
    if (track === "main") {
      this._seek(time);
      this._drag = { type: "seek", trackEl: captureEl };
    } else {
      const distStart = Math.abs(time - this.start);
      const distEnd = Math.abs(time - this.end);
      if (distStart <= distEnd) {
        this.setRange(time, Math.max(this.end, time + this.minGap));
        this._drag = { type: "start", trackEl: captureEl };
      } else {
        this.setRange(this.start, Math.max(time, this.start + this.minGap));
        this._drag = { type: "end", trackEl: captureEl };
      }
    }
    captureEl.setPointerCapture(event.pointerId);
    captureEl.addEventListener("pointermove", this._onPointerMove);
    captureEl.addEventListener("pointerup", this._onPointerUp);
    captureEl.addEventListener("pointercancel", this._onPointerUp);
  }

  _onHandlePointerDown(event, edge) {
    if (!this.duration) return;
    event.preventDefault();
    event.stopPropagation();
    const captureEl = this._els.stack || this._els.clipTrack;
    this._drag = { type: edge, trackEl: captureEl };
    captureEl.setPointerCapture(event.pointerId);
    captureEl.addEventListener("pointermove", this._onPointerMove);
    captureEl.addEventListener("pointerup", this._onPointerUp);
    captureEl.addEventListener("pointercancel", this._onPointerUp);
  }

  _onRangeBodyPointerDown(event) {
    if (!this.duration) return;
    event.preventDefault();
    event.stopPropagation();
    const captureEl = this._els.stack || this._els.clipTrack;
    const time = this._timeFromClientX(event.clientX);
    this._drag = {
      type: "move",
      trackEl: captureEl,
      offset: time - this.start,
      span: this.end - this.start,
    };
    captureEl.setPointerCapture(event.pointerId);
    captureEl.addEventListener("pointermove", this._onPointerMove);
    captureEl.addEventListener("pointerup", this._onPointerUp);
    captureEl.addEventListener("pointercancel", this._onPointerUp);
  }

  _onPointerMove = (event) => {
    if (!this._drag) return;
    const time = this._timeFromClientX(event.clientX, this._drag.trackEl);
    if (this._drag.type === "seek") {
      this._seek(time);
      return;
    }
    if (this._drag.type === "start") {
      this.setRange(Math.min(time, this.end - this.minGap), this.end);
      return;
    }
    if (this._drag.type === "end") {
      this.setRange(this.start, Math.max(time, this.start + this.minGap));
      return;
    }
    if (this._drag.type === "move") {
      const span = this._drag.span;
      let start = time - this._drag.offset;
      start = this._clamp(start, 0, this.duration - span);
      this.setRange(start, start + span);
    }
  };

  _onPointerUp = (event) => {
    if (!this._drag) return;
    const trackEl = this._drag.trackEl;
    trackEl.releasePointerCapture(event.pointerId);
    trackEl.removeEventListener("pointermove", this._onPointerMove);
    trackEl.removeEventListener("pointerup", this._onPointerUp);
    trackEl.removeEventListener("pointercancel", this._onPointerUp);
    this._drag = null;
  };

  _seek(time) {
    const clamped = this._clamp(time, 0, this.duration || time);
    if (this.video) this.video.currentTime = clamped;
    this._renderPlayhead(clamped);
    this.onSeek(clamped);
  }

  _timeFromClientX(clientX) {
    const trackEl = this._els.stack || this._els.mainTrack;
    const rect = trackEl.getBoundingClientRect();
    const ratio = this._clamp((clientX - rect.left) / rect.width, 0, 1);
    return ratio * (this.duration || 1);
  }

  _clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  static _safePlay(video) {
    if (!video) return;
    const result = video.play();
    if (result?.catch) {
      result.catch((error) => {
        if (error.name !== "AbortError") console.warn("Video play failed:", error);
      });
    }
  }

  static formatTime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    return `${minutes}:${String(secs).padStart(2, "0")}`;
  }

  static parseTime(value) {
    const parts = String(value || "").split(":").map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    return Number(value) || 0;
  }
}

window.ClipTimeline = ClipTimeline;
