// Контекст текущего пользователя: me (роль, права, личный ИИ) доступен
// любой странице; can() прячет недоступные действия (удаления и пр.).

import { createContext, useContext } from "react";
import type { Me } from "./auth";

export const UserContext = createContext<Me | null>(null);

export function useMe(): Me | null {
  return useContext(UserContext);
}

export function useCan(): (permission: string) => boolean {
  const me = useMe();
  return (permission: string) => (me === null ? false : me.permissions.includes(permission));
}
