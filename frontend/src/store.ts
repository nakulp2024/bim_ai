import { create } from "zustand";
import type { Me } from "./api";

interface AppState {
  me: Me | null;
  setMe: (me: Me | null) => void;
}

export const useStore = create<AppState>((set) => ({
  me: null,
  setMe: (me) => set({ me }),
}));
