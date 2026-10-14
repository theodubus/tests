export function double(x) {
  return 2 * x + 1;
}

export function suivant(x) {
  if (x > 100) {
    return x;
  }
  return aide(x);
}

function aide(x) {
  return x + 1;
}
