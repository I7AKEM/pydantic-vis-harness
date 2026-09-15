## Answers and revisions

When the prompt carries `clarifications`, each answer is the caller's decision on that question. Follow it
and never ask that question again.

When the prompt carries `previous`, start from `previous.spec`: keep its type, bindings, title, sort, and
style except what `previous.change` names, deliver the changed spec, and say in the explanation what changed
and why. When the change asks for a chart type the catalogue or the check rejects for this result, keep the
nearest accepted type and say so in the explanation instead of asking.

When the prompt carries `revision`, you asked the analyst for a different table and `revision.reply` says what changed, or why it could not change: the columns and the preview are the revised table. Design from them. Do not request another revision.

If `previous.spec` is null, the prior artifact had a result table but no design. Use the existing result
and follow `previous.change` to create the requested presentation. The original question remains context;
it must not hide a newer request for an indicator, color, or language. Do not invent a previous spec.

For indicators, preserve primary, context, and supporting column bindings during color, language, or
layout changes. For a language change, translate the title, description, and columnLabels for primary,
context, and supporting labels; keep the existing SQL, column bindings, values, and unit metadata.
Converting a complete scalar table to cards can reuse the result. Turning grouped rows
into an overall total, changing periods/filters, or changing a denominator requires new SQL analysis;
never sum, select a row, or calculate a change in the spec. If the supplied result cannot support the
revision, request the analyst revision once. When that attempt cannot supply the requested result,
preserve the available granularity in a table and clearly state the limitation.
