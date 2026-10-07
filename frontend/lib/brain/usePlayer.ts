"use client";

import { useEffect } from "react";
import { api } from "@/lib/api";
import { useBrainPlayer } from "./store";

const POLL_MS = 2000;

/**
 * The shared event player. Polls /brain/events since the last id every 2 s into a queue (never dropping an event) and plays
 * one event at a time: about 700 ms apart, about 350 ms when more than 8 are waiting. Mount it once per page that draws the brain.
 */
export function useBrainEventPlayer(enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let pollTimer: ReturnType<typeof setTimeout>;
    let playTimer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const st = useBrainPlayer.getState();
        if (st.cursor === null) {
          // First contact: start from "now". History is only played on request (replay) or when new events arrive.
          const from = st.replayFrom;
          const r = await api.brainEvents(null, from ? 200 : 1);
          if (!alive) return;
          if (from) {
            // a replay was requested before this page mounted: play it from its first event
            useBrainPlayer.getState().enqueue(r.events.filter((e) => e.id >= from));
            useBrainPlayer.setState({ replayFrom: null });
            if (!r.events.length) useBrainPlayer.getState().setCursor("");
          } else useBrainPlayer.getState().setCursor(r.last_id ?? "");
        } else {
          const r = await api.brainEvents(st.cursor || null, 200);
          if (alive && r.events.length) useBrainPlayer.getState().enqueue(r.events);
        }
      } catch {
        /* the offline banner reports it; keep polling */
      }
      if (alive && !document.hidden) pollTimer = setTimeout(poll, POLL_MS);
      else if (alive) pollTimer = setTimeout(poll, POLL_MS * 2);
    };

    const play = () => {
      if (!alive) return;
      const st = useBrainPlayer.getState();
      const e = document.hidden ? null : st.playNext();
      const wait = st.queue.length > 8 ? 350 : 700;
      if (!e && useBrainPlayer.getState().mode !== "idle" && st.queue.length === 0) {
        // settle back to idle a moment after the last event
        playTimer = setTimeout(() => {
          if (useBrainPlayer.getState().queue.length === 0) useBrainPlayer.getState().setMode("idle");
          play();
        }, 1800);
        return;
      }
      playTimer = setTimeout(play, e ? wait : 250);
    };

    poll();
    play();
    return () => {
      alive = false;
      clearTimeout(pollTimer);
      clearTimeout(playTimer);
    };
  }, [enabled]);
}
