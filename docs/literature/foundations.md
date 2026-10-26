# Foundations: what the design borrows and where the numbers come from

## Simulation lineage

This bibliography is included in Git; locally held reading PDFs are ignored.

- **Brahms**: work practice as situated activity. Agents hold beliefs distinct from facts, belong to
  groups, occupy locations, use artifacts, communicate and get interrupted. Adopted as concepts (Person, Location,
  Artifact, Message, LatentState in the ontology), not as the Brahms language.
- **VDT, Virtual Design Team** (Jin and Levitt 1996; Nissen and Levitt WP077): organizations as information
  processors with bounded capacity, coordination and exception queues, dependencies and rework. Adopted in the
  process world: capacity pools per role, waiting separated from labor, exceptions and hand-offs as first-class
  metrics.
- **AnyLogic multimethod modeling**: agents, process queues and aggregate feedback in one model.
  Adopted as the shape of the kernel (hourly clock, scheduler, capacity) with an independent engine.
- Architectural references without validation claims: YC-Bench (persistent executive agents, long-horizon simulated
  time), Emergence World (product reference only).

## Occupational vocabulary

O*NET 31.0 (U.S. Department of Labor, CC BY 4.0): 1,016 occupations, 41 generalized, 332 intermediate and 2,087
detailed work activities, 18,838 task statements. Roles in every instance are bound to O*NET-SOC occupations and
activities to detailed work activities, so roles in different companies share a vocabulary. O*NET provides no
durations or workflow order; those come from each instance's data. Raw tables are unchanged; bindings are authored
extensions not endorsed by USDOL/ETA.

## Employee digital twins: design choices

The workforce model separates persistent traits from changing latent states.
These are modeling choices; accuracy is assessed in [validation](../validation.md).

- A fixed trait layer sets the baseline, while kernel-owned dynamics update weekly states.
- Baseline plus deviation with inertia is specified in `instances/trip/calibration/dynamics.yaml`.
- A language-model seat may choose actions, but cannot replace the kernel's state dynamics.
- `instances/trip/calibration/priors.yaml` records sources and authored assumptions for each parameter.

## Sources behind the Trip.com priors

Each parameter in `instances/trip/calibration/priors.yaml` cites its source inline. The main ones: the 2015 Ctrip
full-time work-from-home experiment (Bloom, Liang, Roberts and Ying, QJE 2015) for the attrition hazard ratio,
take-up and attitude effects; turnover meta-analyses (Griffeth, Hom and Gaertner 2000; Rubenstein et al. 2018;
Meyer et al. 2002 for commitment); commuting and job mobility (van Ommeren and Gutierrez-i-Puigarnau 2011;
Chatterjee et al. 2020); telecommuting and work-family conflict (Gajendran and Harrison 2007; Allen, Golden and
Shockley 2015); the Survey of Working Arrangements and Attitudes (Barrero, Bloom and Davis 2021) for desired home
days and their value; willingness to pay for flexible work (Mas and Pallais 2017; Maestas et al. 2023); peer
comparison (Card, Mas, Moretti and Saez 2012; Adams 1965); tenure and turnover (Farber 1994); performance-rating
stability (Sturman, Cheramie and Cashen 2005); survey reliability (Wanous, Reichers and Hudy 1997); industry
turnover and promotion rates (Aon Hewitt, Mercer, SHRM benchmarks).

## Modeling boundaries

- Policies choose actions; the kernel owns time, capacity, state dynamics and accounting.
- Employee models are distinct from any AI tools introduced into a simulated firm.
- Protected demographic fields are editable and visible in data, but excluded from behavioral functions and prompts.
- Every authored assumption carries a source or is marked "authored" in the priors file.
