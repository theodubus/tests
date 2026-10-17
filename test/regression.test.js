import { expect, test } from "vitest";
import { double } from "../src/calc.js";

test("double de trois", () => {
  expect(double(3)).toBe(6);
});
