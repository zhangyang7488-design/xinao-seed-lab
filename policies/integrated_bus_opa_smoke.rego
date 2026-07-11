# Minimal OPA/Conftest-style smoke policy for integrated_bus evolution_weld.
package xinao.integrated_bus_opa_smoke

default allow := false

allow if {
    input.thin_glue == "integrated_bus_smoke"
    input.invoke_ok == true
}

# Conftest-style deny gate (empty set == pass).
deny contains msg if {
    input.completion_requested == true
    input.object_preserved != true
    msg := "completion_requested_without_object_preserved"
}