from collections import deque

class DefaultStackSmePathInfo:
    def __init__(self, repo, submodel_id=None, id_short_path=None):
        self._referable_stack = deque()
        self.repo = repo
        self.submodel_id = submodel_id
        self.base_id_short_path = id_short_path

    def get_submodel_id(self):
        if self.submodel_id is None and len(self._referable_stack) > 0:
            ref = self._referable_stack[0]
            if hasattr(ref, 'id'):
                self.submodel_id = ref.id
        return self.submodel_id

    def _build_path_from_stack(self):
        if not self._referable_stack:
            return ""

        builder = []
        ref_iter = iter(self._referable_stack)
        
        try:
            first = next(ref_iter)
        except StopIteration:
            return ""

        current_list = first if hasattr(first, 'value') and isinstance(first.value, list) else None

        for referable in ref_iter:
            if current_list is not None:
                try:
                    idx = current_list.value.index(referable)
                    builder.append(f"[{idx}]")
                except ValueError:
                    pass
            else:
                builder.append(referable.id_short)

            if hasattr(referable, 'value') and isinstance(referable.value, list):
                current_list = referable
            else:
                current_list = None
                if referable != self._referable_stack[-1]:
                    builder.append(".")

        return "".join(builder)

    def get_id_short_path(self):
        stack_path = self._build_path_from_stack()
        
        if self.base_id_short_path:
            if not stack_path:
                return self.base_id_short_path
            else:
                return f"{self.base_id_short_path}.{stack_path}"
        else:
            return stack_path

    def offer(self, referable):
        self._referable_stack.append(referable)

    def pop(self):
        if self._referable_stack:
            self._referable_stack.pop()

    def repository(self):
        return self.repo