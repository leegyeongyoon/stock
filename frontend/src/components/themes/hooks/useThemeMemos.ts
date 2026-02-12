"use client";

import { useState, useEffect } from "react";

export default function useThemeMemos() {
  const [memos, setMemos] = useState<Record<string, string>>({});

  useEffect(() => {
    const stored = localStorage.getItem("themeMemos");
    if (stored) {
      try {
        setMemos(JSON.parse(stored));
      } catch {
        setMemos({});
      }
    }
  }, []);

  const setMemo = (themeCode: string, memo: string) => {
    const updated = { ...memos, [themeCode]: memo };
    if (!memo) delete updated[themeCode];
    setMemos(updated);
    localStorage.setItem("themeMemos", JSON.stringify(updated));
  };

  const getMemo = (themeCode: string) => memos[themeCode] || "";

  return { memos, setMemo, getMemo };
}
