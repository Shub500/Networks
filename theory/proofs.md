# Screen then Restore: proofs

Section 1 proves the witness reduction in Section 2.2 of the paper. Sections 2, 3 and 4 prove Propositions 1, 2 and 3. Sections 5 and 6 establish the reuse and stopping properties used by Algorithm 1.

## Setting

Let $`G=(V,E)`$ be a fixed simple undirected graph, $`C\ge1`$ an integer, and $`D\subseteq V`$ a feasible disabled set. Write $`\mathcal R(D)`$ for the connected components of $`G[V\setminus D]`$; feasibility means $`|R|\le C`$ for every $`R\in\mathcal R(D)`$. For $`u\in D`$, let $`S(u)`$ contain the residual components adjacent to $`u`$, and define its single-restoration size

```math
M(u)=1+\sum_{R\in S(u)}|R|.
```

An exchange $`(U,X)`$ restores $`U\subseteq D`$ and deletes $`X\subseteq V\setminus D`$, producing $`D'=(D\setminus U)\cup X`$ with gain $`|U|-|X|`$. RG saturation means $`M(u)>C`$ for every $`u\in D`$. Pair closure means RG saturation and the absence of any feasible $`(2,1)`$ exchange.

## 1. Unit-gain witnesses

**Statement.** For a fixed deletion set $`X`$ of size $`d`$, an improving exchange exists if and only if a feasible restoration set of size $`d+1`$ exists.

**Proof.** If $`U`$ is feasible and $`U'\subseteq U`$, the residual graph after restoring $`U'`$ is an induced subgraph of the graph after restoring $`U`$. Removing vertices cannot enlarge a connected component, so $`U'`$ is feasible. An improving exchange has $`|U|>d`$ and therefore contains a feasible subset of size $`d+1`$. Conversely, such a subset has gain one. Given a particular larger feasible set $`U`$, its remaining vertices may be restored in any order: every intermediate graph is an induced subgraph of the feasible final graph. Thus unit-gain witnesses preserve the existence of an improving move at each fixed $`X`$. $`\square`$

Algorithm 1 uses $`(2,1)`$ witnesses for one deletion and $`(3,2)`$ witnesses for two deletions. Its greedy extension of a witness chooses a feasible larger set; the existence result does not require that this choice maximize the number restored.

## 2. Proposition 1: merged-size screening and pair reduction

**Statement.** Assume RG saturation. If $`(\{u,v\},\{x\})`$ is feasible and $`x\in R`$, then $`R\in S(u)\cap S(v)`$ and

```math
M(u)-|R|\le C,\qquad M(v)-|R|\le C.
```

These inequalities are sharp when only the integer values $`C,|R|,M(u),M(v)`$ are known: every tuple with $`1\le |R|\le C`$ and $`C<M(u),M(v)\le C+|R|`$ admits a feasible realization. With $`\Delta_u=M(u)-C`$, the number of adjacent components on which $`u`$ passes the screen is at most

```math
\min\left\{|S(u)|,\left\lfloor\frac{M(u)-1}{\Delta_u}\right\rfloor\right\},
```

and is zero if $`M(u)>2C`$. If a component has $`N\ge2`$ incident candidates and $`e`$ survive, its retained pair fraction is at most $`(e/N)^2`$.

**Proof of necessity.** By Section 1, restoring $`u`$ alone after deleting $`x`$ must be feasible. If $`R\notin S(u)`$, deleting $`x`$ leaves the overloaded connected region of size $`M(u)>C`$ unchanged, a contradiction. The vertex $`u`$ and all components in $`S(u)\setminus\{R\}`$ remain connected after deleting $`x`$, with total size $`M(u)-|R|`$. This size must be at most $`C`$. The same argument applies to $`v`$.

**Proof of sharpness.** Fix integers $`1\le r\le C`$, $`C<m_u,m_v\le C+r`$. Construct $`R`$ as a star on $`r`$ vertices centered at $`x`$ (a singleton when $`r=1`$). Join $`u`$ and $`v`$ only to $`x`$ within $`R`$, omit the edge $`uv`$, and give $`u,v`$ disjoint private neighboring components of sizes $`m_u-1-r`$ and $`m_v-1-r`$. A zero size means that no component is added. These sizes lie between zero and $`C-1`$, so the starting cut $`D=\{u,v\}`$ is feasible and RG-saturated, with $`M(u)=m_u`$ and $`M(v)=m_v`$. Deleting $`x`$ leaves singleton star leaves and two separate restored regions of sizes $`m_u-r\le C`$ and $`m_v-r\le C`$. Thus every scalar tuple passing the screen has a realization with a feasible pair. Additional topology can still make a passing pair infeasible; the quotient check decides that question.

**Proof of the counting bounds.** Every surviving adjacent component has size at least $`\Delta_u`$, and the sizes of all adjacent components sum to $`M(u)-1`$. This gives the stated incidence bound. Since each component has size at most $`C`$, none can survive when $`\Delta_u>C`$. If $`e<2`$, no pair remains. For $`2\le e\le N`$,

```math
\frac{\binom e2}{\binom N2}=\frac{e(e-1)}{N(N-1)}\le\frac{e^2}{N^2}.
```

At $`C=1`$, each residual component is a singleton. The screen and RG saturation force each restored endpoint to have exactly one residual neighbor, recovering the one-tight condition for an independent-set improvement. $`\square`$

## 3. Proposition 2: singleton responses and the shared bridge

### 3.1 Exact singleton gate

For each $`R\in\mathcal R(D)`$ let $`X_R=X\cap R`$. Deleting $`X_R`$ leaves connected fragments of $`R`$. Let $`a_R(u,X_R)`$ be the sum of the sizes of the distinct surviving fragments adjacent to $`u`$, and set $`\delta_R(u,X_R)=|R|-a_R(u,X_R)`$. Then

```math
m_X(u)=M(u)-\sum_{R\in S(u)}\delta_R(u,X_R)
```

is exactly the connected-component size obtained by restoring $`u`$ alone after deleting $`X`$.

**Proof.** Distinct residual components have no edges between them. After deletion, restoring $`u`$ joins precisely its adjacent surviving fragments through $`u`$; each fragment is counted once. Thus the size is $`1+\sum_{R\in S(u)}a_R(u,X_R)`$, which equals the displayed expression. If $`X_R=\varnothing`$, then $`a_R(u,X_R)=|R|`$ and its contribution to the shed mass is zero.

Let $`\mathcal R_X=\{R:X_R\ne\varnothing\}`$, and define

```math
A_X=\left\{u\in D:S(u)\cap\mathcal R_X\ne\varnothing,\quad M(u)-\sum_{R\in S(u)\cap\mathcal R_X}|R|\le C\right\},
```

```math
S_X=\{u\in A_X:m_X(u)\le C\}.
```

Under RG saturation, an individually feasible endpoint must touch a component in $`\mathcal R_X`$, and deleting all such components gives a lower bound on its actual restored size. Hence it belongs to $`A_X`$. By downward heredity every endpoint of a feasible restoration set $`U`$ is individually feasible, so $`U\subseteq S_X`$. If $`|S_X|\le|X|`$, no improving exchange is possible. $`\square`$

For one deleted vertex $`x\in R`$, a low-link DFS gives the fragments without a new graph traversal per endpoint. For a nonroot $`x`$, child subtrees with $`\mathrm{low}(c)\ge\mathrm{tin}(x)`$ are separate fragments; the remaining vertices form the complementary fragment, if nonempty. At a DFS root, each child subtree is a fragment. A singleton leaves none. DFS intervals locate an endpoint's surviving attachments, giving exact shed mass. Query work includes inspecting attachments and distinct fragments. For two deletions in the same component, the implementation computes their joint fragments; summing two separate single-deletion responses would be incorrect.

### 3.2 Shared-bridge condition

**Statement.** Suppose $`D`$ is pair-closed. Every feasible $`(3,2)`$ exchange with splitters $`x\in R`$, $`y\in Q`$, $`R\ne Q`$, restores an endpoint $`u`$ adjacent to both $`R`$ and $`Q`$, satisfying

```math
\delta_R(u,\{x\})+\delta_Q(u,\{y\})\ge M(u)-C.
```

**Proof.** By RG saturation, each of the three restored endpoints touches $`R`$ or $`Q`$. Suppose none touches both. Two endpoints then touch only the same one, say $`R`$. Remove the third endpoint from the feasible exchanged graph. The remaining two endpoints still form feasible components. Restoring $`y`$ affects only $`Q`$, which neither endpoint touches; it reconstructs an originally feasible component and cannot join their regions. The two endpoints therefore give a feasible $`(2,1)`$ exchange deleting only $`x`$, contradicting pair closure. A shared endpoint $`u`$ exists. Its individual restored size is at most $`C`$ by Section 3.1, which gives the inequality. At $`C=1`$, this shared endpoint has exactly the two residual neighbors $`x,y`$, the corresponding two-tight condition. $`\square`$

Upper bounds on the two shed masses can therefore exclude splitter contexts before triple construction. Algorithm 1 applies this rule after completed pair closure. Its same-component search uses $`|R|\le\tau`$ with $`\tau=35`$.

## 4. Proposition 3: exact quotient evaluation and compatible batches

### 4.1 Supernode quotient

For a candidate $`(U,X)`$, contract each surviving fragment of a deleted component and each untouched component incident to $`U`$ into a supernode weighted by its size. Give each restored vertex unit weight. Retain all edges between restored vertices and all incidences between a restored vertex and a supernode. The load of a connected quotient component is the sum of its distinct vertex weights.

**Proof.** Each contracted set is internally connected, and different such sets have no residual edges between them. Every connection between the sets therefore passes through a restored vertex and is retained in the quotient. Contraction preserves connectedness, and summing distinct supernode weights counts every physical vertex exactly once. Quotient-component loads consequently equal the affected physical component sizes. Any component omitted from the quotient is unchanged or a fragment of an originally feasible component, so remains within $`C`$. The candidate is feasible exactly when every connected quotient component has total weight at most $`C`$. $`\square`$

### 4.2 Compatible batches and unchanged indices

Suppose feasible moves $`(U_i,X_i)`$ are all evaluated on the same plan $`D`$. Define their touched components by

```math
\mathcal T_i=\{R:R\cap X_i\ne\varnothing\}\cup\bigcup_{u\in U_i}S(u).
```

Assume the $`U_i`$ are pairwise disjoint, the $`\mathcal T_i`$ are pairwise disjoint, and no edge joins $`U_i`$ to $`U_j`$ for $`i\ne j`$. Then the union exchange is feasible, its gain is $`\sum_i(|U_i|-|X_i|)`$, and fragment indices for components outside $`\bigcup_i\mathcal T_i`$ remain valid.

**Proof.** Every changed residual vertex of move $`i`$ lies in its touched components or in $`U_i`$. Distinct old residual components have no connecting edge. The footprint and edge assumptions rule out every new connection between the changed regions of two moves. Their separate feasible component sizes therefore remain unchanged under the union. The deleted sets $`X_i`$ are disjoint because their containing components are disjoint; the restored sets are disjoint by assumption. Hence gains add. Outside the touched components, the retained vertex sets and induced edges do not change, preserving the component indices. Failed-search records have additional dependencies, checked as described below. $`\square`$

## 5. Exact reuse and failed searches

A fragment index depends on the fixed graph and exact component membership. An endpoint response additionally identifies its splitter and endpoint. Matching these data preserves the local response; external component masses are read from the current plan. A stored graph alias is reused only after exact equality has been established, and only while the aliased object is immutable.

A failed-family certificate records a completed search, its graph and cap, exact local members, candidate identities, and every vertex in each external component adjacent to a candidate. It can skip a later search when local members and candidates match, the candidates are still disabled, and all recorded external vertices remain retained. For every old trial, its overloaded connected subgraph is then present in the new trial. Added vertices or merged components cannot reduce its size. Thus the same trial still fails. Discarding a certificate removes a reuse opportunity without changing this argument.

An additional margin rule permits some loss from external components adjacent to only one candidate. Components shared by candidates must remain intact. If an exclusive component loses any vertex, charge its entire old size to its candidate, including vertices that may become detached. For a trial restoring $`k`$ candidates, the sum of the $`k`$ largest candidate charges bounds its possible load decrease. If this bound is strictly smaller than a positive failure margin valid for every trial in the completed family, at least one oversized component remains in every trial. The record therefore remains valid. The implemented $`(2,1)`$ margin covers individually infeasible endpoints and all pairs of individually feasible endpoints for every splitter; an incomplete or successful search supplies no such record.

## 6. Greedy extension, neutral continuation and anytime stopping

**Maximal one-deletion extension.** From an RG-saturated plan, a completed greedy extension at one splitter produces an RG-saturated plan. Any omitted endpoint was infeasible when considered and stays infeasible as more endpoints return, by graph inclusion. Restoring the splitter would recreate the original overloaded single-restoration region of an accepted endpoint. This argument requires a completed maximal extension; a batch uses the ordinary RG check.

**Neutral continuation.** From a pair-closed plan, a feasible $`(1,1)`$ swap remains RG-saturated. A newly feasible restoration would give an improving $`(2,1)`$ move in the original plan, while restoring the new splitter would give a forbidden single restoration. If a subsequent pair repair succeeds, the composition has net $`(3,2)`$ form. Indeed, if its deletion removes the first restored endpoint, the final move is an original $`(2,1)`$ improvement; if its restorations include the first splitter, the final move is an original $`(2,1)`$ improvement. Both cancellations together give an original single restoration. All contradict pair closure. The three restored endpoints and two splitters are therefore distinct. Only the verified net improvement is accepted.

**Anytime output.** The input plan is checked for feasibility. Candidate construction, component indexing, cache operations, scans and complete-plan verification are charged to one clock taking the maximum of elapsed wall and process-CPU time. An accepted candidate passes a fresh whole-graph component check within its allowance and is no larger than the best accepted plan. A completed scan can choose a different plan of equal size under its fixed tie order. On timeout the algorithm returns the last verified plan, including the input if no improvement was accepted. Closure is reported only after the corresponding search finishes; Class-II closure refers to its stated component-size limit.
