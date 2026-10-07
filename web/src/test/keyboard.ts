import type { UserEvent } from "@testing-library/user-event";

// A key pressed as a person does: released after the page has handled it, so a handler that runs in a timeout (Radix
// moves roving focus in one) still sees the key down. `user.keyboard("{Key}")` releases it at once.
export const press = async (user: UserEvent, key: string) => {
  await user.keyboard(`{${key}>}`);
  await user.keyboard(`{/${key}}`);
};
