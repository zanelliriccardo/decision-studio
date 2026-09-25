# Debate fra teorie — progetto

## Il malinteso da evitare

L'implementazione ovvia è due agenti che discutono: T1 argomenta, T3 ribatte, T1
replica. Produce un transcript piacevole e quasi nessun valore decisionale.
Il problema è che entrambi gli agenti sono lo stesso modello, quindi il "dibattito"
misura chi ha ricevuto il prompt migliore, non quale teoria regge.

La domanda utile non è **"quale teoria vince"** — quello è il ranking, esiste già,
e con `adjusted_score` tiene già conto delle obiezioni.

La domanda utile è: **"cosa le distingue, e come faccio a scoprire quale delle due
è vera?"**

## Struttura in tre parti, due deterministiche

### 1. Sovrapposizione strutturale — nessun LLM

Ho già `theory_claim` e `theory_edge` normalizzati. Il confronto si calcola:

```
condivisi   = claim(T1) ∩ claim(T3),  edge(T1) ∩ edge(T3)
divergenti  = differenza simmetrica
jaccard     = |∩| / |∪|
```

Questo produce subito il risultato più importante e più spesso ignorato:

- **Jaccard > 0.7** → *non sono teorie concorrenti*, sono la stessa storia
  raccontata in due modi. Il debate si ferma qui e lo dice. Metterle a confronto
  sarebbe teatro.
- **Jaccard < 0.2** → non competono nemmeno: parlano di cose diverse. Possono
  essere entrambe vere. Anche questo va detto, perché la presentazione a lista
  suggerisce implicitamente che siano alternative.
- **Nel mezzo** → c'è un vero disaccordo. Si continua.

Deterministico, verificabile, gratis.

### 2. Il crux — dove si separano

Il punto in cui le due catene causali divergono. Anche questo in buona parte
calcolabile: il claim o l'edge che sta in una e non nell'altra, e che è più vicino
alla conclusione condivisa.

L'LLM serve solo a esprimerlo in una frase: *"entrambe accettano che il freeze sia
slittato; T1 sostiene che comprima l'integrazione, T3 che il buffer assorba"*.

### 3. L'osservazione discriminante — l'unico vero output LLM

*Quale osservazione avrebbe esito diverso a seconda di quale teoria è vera?*

Questo è il pezzo che vale, e si collega direttamente a quello che ho già
costruito: **il discriminante è un tripwire o un esperimento sul campo, già
pronto per essere generato.** Il debate non finisce con un vincitore, finisce
con una cosa da andare a guardare.

Se non esiste alcuna osservazione discriminante entro la scadenza, è un risultato
di prima classe: significa che la distinzione fra le due teorie non è decidibile
in tempo utile, e che va scelta l'opzione robusta a entrambe. È l'informazione
più preziosa che il debate possa produrre e quella che un dibattito narrativo
non produce mai.

## Cosa aggiungerei allo schema

```
theory_debate
  id, project_id, theory_a_id, theory_b_id
  overlap_jaccard        float      calcolato, non generato
  relation               varchar    same_story | competing | orthogonal
  shared_claim_ids       JSON
  divergent_claim_ids    JSON
  crux                   text       dove si separano
  discriminator          text       cosa osservare
  discriminator_feasible bool
  evidence_favours       varchar    a | b | neither
  both_possible          bool       non mutuamente esclusive
  created_at
```

`relation` e `overlap_jaccard` si calcolano prima di chiamare il modello, e se la
relazione è `same_story` **non lo si chiama affatto**.

## Perché in questo ordine

Struttura prima, LLM dopo. Se calcolo la sovrapposizione per prima:

- risparmio la chiamata nei casi degeneri, che sono frequenti — il validatore
  già scarta i duplicati sopra 0.8 di sovrapposizione, quindi teorie molto simili
  arrivano comunque in coppia;
- il modello riceve un fatto invece di doverlo dedurre, e non può sbagliarlo;
- l'output è auditabile: il numero viene dal grafo, non da un giudizio.

È lo stesso principio del resto del sistema — l'aritmetica in codice, al modello
solo il giudizio sul significato.

## Costo

Circa una giornata. Una tabella, una funzione pura di confronto insiemistico
(testabile senza DB né provider), un prompt, un endpoint, un pannello di
confronto affiancato.

## Il rischio

Che diventi un generatore di transcript. La difesa è nello schema: non c'è un
campo `transcript`. I campi sono `crux`, `discriminator`, `both_possible` — se
l'output non riempie quelli, non ha prodotto niente, e si vede.
