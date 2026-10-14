import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { mockFetch } from "../test/fetch";
import { makeTask } from "../test/fixtures";
import { qk, useConfirmText, useCreateRound } from "./hooks";

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

test("task mutations write the returned task into the cache", async () => {
  const task = makeTask({ status: "ready" });
  const calls = mockFetch({ "PUT /api/tasks/t1/text": task });
  const { client, wrapper } = setup();
  const { result } = renderHook(() => useConfirmText("t1"), { wrapper });
  result.current.mutate("原文。");
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(client.getQueryData(qk.task("t1"))).toEqual(task);
  expect(JSON.parse(calls[0].init?.body as string)).toEqual({ confirmed_text: "原文。" });
});

test("creating a round posts the request body", async () => {
  const calls = mockFetch({ "POST /api/tasks/t1/rounds": makeTask({ status: "generating" }) });
  const { wrapper } = setup();
  const { result } = renderHook(() => useCreateRound("t1"), { wrapper });
  result.current.mutate({ suggestion: { round_id: 3, index: 0 } });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(JSON.parse(calls[0].init?.body as string)).toEqual({ suggestion: { round_id: 3, index: 0 } });
});
