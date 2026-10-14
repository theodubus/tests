import { describe, expect, test } from "vitest";
import { double, suivant } from "../src/calc.js";

describe("calc", () => {
  test("double multiplie par deux", () => {
    expect(double(2)).toBe(4);
  });

  test("suivant ajoute un", () => {
    expect(suivant(1)).toBe(2);
  });
  // FIN DES TESTS
});
