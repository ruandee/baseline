import json
from uuid import uuid4

from evals.run import CORPUS, fixture_identity, load_profile
from patient_memory.auth import synthetic_token
from patient_memory.config import Settings
from patient_memory.objects import ObjectStore

if __name__ == "__main__":
    cfg = Settings()
    objects = ObjectStore(cfg)
    objects.initialize()
    run_id = uuid4()
    identities = [fixture_identity(cfg, run_id, i) for i in range(2)]
    loaded = []
    for i, profile in enumerate(json.loads(CORPUS.read_text())["profiles"]):
        actor = identities[i % 2]
        patient, _ = load_profile(cfg, objects, actor, profile)
        loaded.append({"profile": profile["id"], "patient_id": str(patient),
                       "tenant_id": str(actor.tenant_id), "actor_id": str(actor.principal_id),
                       "token": synthetic_token(actor, cfg)})
    print(json.dumps(loaded, indent=2))
