import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        profit: "#22c55e",
        loss: "#ef4444",
      },
    },
  },
  plugins: [],
};

export default config;
