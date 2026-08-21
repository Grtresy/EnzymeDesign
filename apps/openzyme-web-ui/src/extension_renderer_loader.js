const DIGEST = /^sha256:[0-9a-f]{64}$/;

function requireDigest(value, field) {
  if (typeof value !== "string" || !DIGEST.test(value)) {
    throw new Error(`${field} must be a canonical SHA-256 digest`);
  }
}

export class ExtensionRendererRegistry {
  constructor({ rendererCatalogDigest, entries = [] }) {
    requireDigest(rendererCatalogDigest, "rendererCatalogDigest");
    this.rendererCatalogDigest = rendererCatalogDigest;
    this.entries = new Map();
    for (const entry of entries) {
      if (!entry?.sectionId || this.entries.has(entry.sectionId)) {
        throw new Error("extension renderer section registration is invalid or duplicated");
      }
      requireDigest(entry.sectionContractDigest, `${entry.sectionId}.sectionContractDigest`);
      requireDigest(entry.rendererContractDigest, `${entry.sectionId}.rendererContractDigest`);
      if (!entry.rendererId || typeof entry.render !== "function") {
        throw new Error("extension renderer identity or implementation is missing");
      }
      this.entries.set(entry.sectionId, Object.freeze({ ...entry }));
    }
  }

  resolve(projection, { expectedRendererCatalogDigest }) {
    requireDigest(expectedRendererCatalogDigest, "expectedRendererCatalogDigest");
    const blockers = [];
    const renderedSections = {};
    if (expectedRendererCatalogDigest !== this.rendererCatalogDigest) {
      blockers.push({
        code: "renderer_catalog_drift",
        expected: expectedRendererCatalogDigest,
        observed: this.rendererCatalogDigest,
      });
    }
    for (const [sectionId, section] of Object.entries(projection.extensions)) {
      const renderer = this.entries.get(sectionId);
      if (!renderer) {
        blockers.push({ code: "extension_renderer_missing", section_id: sectionId });
        continue;
      }
      if (renderer.sectionContractDigest !== section.section_contract_digest) {
        blockers.push({ code: "extension_section_contract_drift", section_id: sectionId });
        continue;
      }
      renderedSections[sectionId] = renderer.render(structuredClone(section.payload), {
        nextCursor: section.next_cursor,
        projectionDigest: section.projection_digest,
        rendererId: renderer.rendererId,
        rendererContractDigest: renderer.rendererContractDigest,
      });
    }
    return {
      blockers,
      mutationAllowed: blockers.length === 0,
      renderedSections,
    };
  }
}
