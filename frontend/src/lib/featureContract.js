/**
 * Which form fields the serving model reads (`GET /model/feature-contract`).
 *
 * The form marks a field "not used in this score" only when the contract of
 * the model actually serving says so. Until the contract loads, the form's own
 * marks (written for the trained 3-feature model) are used.
 */

/** Names of intake fields the serving model does not read. */
export function unusedFieldNames(contract, fallback = []) {
  if (!contract || !Array.isArray(contract.collected_unused)) return new Set(fallback);
  return new Set(contract.collected_unused.map((field) => field.name));
}

/** A short line describing the serving engine's inputs, for the form header. */
export function contractSummary(contract) {
  if (!contract) return null;
  const names = (contract.model_features ?? []).map((feature) => feature.label);
  if (contract.engine === "ml") {
    return `The current model reads ${names.length} features: ${names.join(", ")}. Fields marked below are recorded but do not change the score.`;
  }
  return "The fallback formula is serving and reads every scoring field with hand-set weights.";
}
