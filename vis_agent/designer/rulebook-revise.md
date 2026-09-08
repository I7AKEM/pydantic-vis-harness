## Answers and revisions

When the prompt carries `clarifications`, each answer is the caller's decision on that question. Follow it
and never ask that question again.

When the prompt carries `previous`, start from `previous.spec`: keep its type, bindings, title, sort, and
style except what `previous.change` names, deliver the changed spec, and say in the explanation what changed
and why. When the change asks for a chart type the catalogue or the check rejects for this result, keep the
nearest accepted type and say so in the explanation instead of asking.
