"""Retired unsafe migration entry point; importing this module has no side effects.

Engineering data must use OntoBase's authorized, versioned preview/apply APIs.
Name-based model bindings also require review through ONTOVis resource APIs.
The historical implementation is retained in the review evidence, never executed.
"""


def main():
    raise SystemExit("This migration is disabled: direct database changes bypass permissions, "
                     "version checks and engineering review. Use the audited API workflow.")


if __name__ == '__main__':
    main()
