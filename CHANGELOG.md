***PLEASE PUT ANY COMMITED CONTRIBUTIONS HERE, WITH ANY EFFECTED SYSTEMS***


- Matt @3.5.26
Created repository with proposed layout, due to change, run with frozen flag -m: `python -m src.api.app`
- Matt @4.1.26
  -  Utilized DDD to break out functionality for authorization, built out dependency injection in `dependency.py` allows us to grab account/client/coach/admin records by bearer token just by entering the function scope with `Depends()`
  - fixed models to use a new SQLModelLU class instead of SQLModel, normalizing default factory for last_updated property
  - created new folder `flows` to store system flows for less ambiguity during development, use this to learn unfamiliar workflows
  - fixed some models that were typed as optional, but no default value was provided; ***there may still be more***
  - added TODO's for when all of the models are correctly done
  - Final notes: Run backend with `python -m src.api.app`, src.api has and will retain all business logic for how to use data from src.database.xxxx.models, src.api.auth currently only supports email/pw login/signup, we still need to make it ambiguous for GCP OAuth, the schema currently supports it but I didn't have time today to set it up

- Matt @4.2.26
  - Finished all of the models (~20 from what was leftover)
  - Finished & manually tested initial survey submission endpoint, coach & client /me routes, and coach request submission route
  - Began to build out full CRUD for roles (modifying certs & experiences)