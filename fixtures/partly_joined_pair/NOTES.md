# A pair with one leg already joined

This static two-connector board has one locked `USB_D_P` track and an open
`USB_D_N` connection. Its stage-2 capture names `USB.D` as a `DiffPair`;
the `diff-pairs` phase must select it when either member is open. The original
track is retained exactly, including its width, layer, lock and UUID.

The actual router proof completed N through its reported single-ended fallback,
then the signals phase made no calls. This verifies selection and preservation
of existing copper; it does not certify coupled geometry or impedance. Both
final pad joins were connected and nonviolated under the original project rules.
The test retains the router's reported pair category rather than relabelling
single-ended completion as coupling.
