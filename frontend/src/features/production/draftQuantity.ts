export function compareDraftQuantity(original: string, current: string, allowZero = false) {
  const pattern = allowZero ? /^(0|[1-9]\d{0,17})$/ : /^[1-9]\d{0,17}$/;
  const originalValid = pattern.test(original);
  const currentValid = pattern.test(current);
  return {
    changed: original !== current,
    originalValid,
    currentValid,
    difference: originalValid && currentValid ? (BigInt(current) - BigInt(original)).toString() : undefined,
  };
}
