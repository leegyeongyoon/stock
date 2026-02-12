"use client";

import { useState, useEffect } from "react";

export default function useFavoriteThemes() {
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    const stored = localStorage.getItem("favoriteThemes");
    if (stored) {
      try {
        setFavorites(JSON.parse(stored));
      } catch {
        setFavorites([]);
      }
    }
  }, []);

  const toggleFavorite = (themeCode: string) => {
    setFavorites((prev) => {
      const newFavorites = prev.includes(themeCode)
        ? prev.filter((c) => c !== themeCode)
        : [...prev, themeCode];
      localStorage.setItem("favoriteThemes", JSON.stringify(newFavorites));
      return newFavorites;
    });
  };

  const isFavorite = (themeCode: string) => favorites.includes(themeCode);

  return { favorites, toggleFavorite, isFavorite };
}
