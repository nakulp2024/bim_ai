import { create } from "zustand";
import type { IfcElement } from "./api";

interface AppState {
  projectId: string | null;
  elements: IfcElement[];
  selectedGuid: string | null;
  status: string;
  setProjectId: (id: string | null) => void;
  setElements: (els: IfcElement[]) => void;
  setSelectedGuid: (guid: string | null) => void;
  setStatus: (s: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  projectId: null,
  elements: [],
  selectedGuid: null,
  status: "Idle.",
  setProjectId: (id) => set({ projectId: id }),
  setElements: (els) => set({ elements: els }),
  setSelectedGuid: (guid) => set({ selectedGuid: guid }),
  setStatus: (s) => set({ status: s }),
}));
