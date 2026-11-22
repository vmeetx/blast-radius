"""Which functions may write state that outlives a call: module globals, class attributes, module caches.

Errs towards yes. A yes costs time (the load rule is used instead), a wrong no could cost a miss.
"""
import ast
import itertools

MUTATORS = frozenset(
    "add append appendleft clear discard extend insert pop popitem popleft remove reverse setdefault sort update "
    "__setitem__ __delitem__ __setattr__ __delattr__ register cache_clear".split()
)
DECORATORS_KEEPING_NOTHING = frozenset("property classmethod staticmethod abc.abstractmethod abstractmethod t.overload overload wraps functools.wraps".split())
CHANGE_FIRST_ARGUMENT = frozenset("heappush heappop heapreplace heappushpop heapify insort insort_left insort_right shuffle setitem delitem".split())
REACHES_OUT = (ast.Nonlocal, ast.Global)
INNER, SHARED_DEFAULT, MAY_NAME_AN_OLD_OBJECT = (
    tuple(getattr(ast, kind) for kind in kinds.split())
    for kinds in ("Lambda FunctionDef AsyncFunctionDef", "Call Dict DictComp List ListComp Set SetComp", "Name Attribute Subscript Call BoolOp IfExp")
)
CLASS_NAMES = frozenset(("cls", "mcs", "mcls", "klass", "class_", "metacls"))


def class_attribute_names(trees):
    """Names that some class body of the repository gives a value."""
    everything = itertools.chain.from_iterable(map(ast.walk, trees))
    statements = [line for holder in everything if isinstance(holder, ast.ClassDef) for line in holder.body]
    return set().union(*(_names_in(target) for line in statements for target in _given_a_value(line)))


def _names_in(target):
    return {part.id for part in ast.walk(target) if isinstance(part, ast.Name)}


def _given_a_value(statement):
    match statement:
        case ast.Assign(targets=targets):
            return targets
        case ast.AnnAssign(target=target, value=ast.expr()):
            return [target]
    return []


def _names_bound_by(node):
    """Names this one node binds in the scope it stands in."""
    match node:
        case ast.arg(arg=name) | ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.ExceptHandler(name=str(name)):
            yield name
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
            yield name
        case ast.Import(names=renamed) | ast.ImportFrom(names=renamed):
            for alias in renamed:
                yield alias.asname or alias.name.partition(".")[0]


def _bound_names(function):
    """Names local to the function or to a function nested in it."""
    within = iter(ast.walk(function))
    next(within)
    return {name for node in within for name in _names_bound_by(node)}


def _defines(node):
    """Does this node make a function: a def or a lambda?"""
    return isinstance(node, INNER)


def _may_keep(node):
    """A decorator that is not a plain one, or a default value that is made once and then shared."""
    for decorator in getattr(node, "decorator_list", ()):
        # any other decorator may keep results, or what it is given, between calls
        called = ast.unparse(decorator).partition("(")[0]
        if called not in DECORATORS_KEEPING_NOTHING and not called.endswith((".setter", ".getter", ".deleter")):
            return True
    return _defines(node) and any(isinstance(default, SHARED_DEFAULT) for default in (*node.args.defaults, *node.args.kw_defaults))


def _given_names(node):
    """(target, value) pairs of a node that gives names a value."""
    match node:
        case ast.Assign(targets=targets, value=value):
            return [(target, value) for target in targets]
        case ast.AnnAssign(target=target, value=ast.expr() as value) | ast.NamedExpr(target=target, value=value):
            return [(target, value)]
        case ast.For(target=target, iter=value) | ast.comprehension(target=target, iter=value):
            return [(target, value)]
    return []


def writes_state(function, class_attributes):
    """Does this function (an AST node, nested functions included) write lasting state, as far as can be told?"""
    parts = list(ast.walk(function))
    if any(isinstance(part, REACHES_OUT) or _may_keep(part) for part in parts):
        return True
    # what a function inside this one changes of its surroundings may live as long as that function does
    if any(writes_state(part, class_attributes) for part in parts[1:] if _defines(part)):
        return True
    local = _bound_names(function)
    imports = [part for part in parts if isinstance(part, (ast.ImportFrom, ast.Import))]
    imported = set().union(*(_names_bound_by(part) for part in imports))
    lasting = set()

    def outlives(node):
        """May this expression be an object that outlives the call (and is not the instance itself)?"""
        match node:
            case ast.Name(id=name):
                return name not in local or any(name in kept for kept in (lasting, CLASS_NAMES, imported))
            case ast.Attribute(attr=name, value=owner):
                return name in class_attributes or name in ("__class__", "__dict__") or outlives(owner)
            case ast.Subscript(value=owner):
                return outlives(owner)
            case ast.Call(func=ast.Name(id=name)):
                return name in ("type", "globals", "vars", "super")
            case ast.Call(func=ast.Attribute(attr=name, value=owner)):
                return name in ("get", "setdefault", "__new__", "values", "items") and outlives(owner)
            case ast.BoolOp() | ast.IfExp() | ast.NamedExpr():
                return any(outlives(child) for child in ast.iter_child_nodes(node) if isinstance(child, ast.expr))
        return False

    # locals that name a lasting object: two rounds settle chains
    for part in parts * 2:
        for target, value in _given_names(part):
            # a plain call or a fresh literal makes a new object; a bare global function or class is not data
            if isinstance(value, MAY_NAME_AN_OLD_OBJECT) and outlives(value):
                lasting |= _names_in(target)

    def stores(target):
        match target:
            case ast.Tuple(elts=inner) | ast.List(elts=inner):
                return any(map(stores, inner))
            case ast.Starred(value=inner):
                return stores(inner)
            case ast.Attribute(value=ast.Name(id="self")):
                # self.x = ... is the instance's own, whatever the class calls x
                return False
            case ast.Attribute(value=owner) | ast.Subscript(value=owner):
                return outlives(owner)
        return False

    def stored_into(node):
        match node:
            case ast.Assign(targets=targets) | ast.Delete(targets=targets):
                return targets
            case ast.AugAssign(target=target) | ast.AnnAssign(target=target) | ast.For(target=target) | ast.AsyncFor(target=target):
                return [target]
            case ast.withitem(optional_vars=ast.expr() as target):
                return [target]
        return []

    for node in ast.walk(function):
        if any(map(stores, stored_into(node))):
            return True
        match node:
            case ast.AugAssign(target=ast.Name(id=name)) if name in lasting:
                return True
            case ast.Call(func=ast.Name(id="setattr" | "delattr"), args=[first, *_]):
                match first:
                    case ast.Name(id="self"):
                        continue
                if outlives(first):
                    return True
            case ast.Call(func=ast.Name(id=name) | ast.Attribute(attr=name), args=[first, *_]) if name in CHANGE_FIRST_ARGUMENT and outlives(first):
                return True
            case ast.Call(func=ast.Attribute(attr=name, value=owner)) if name in MUTATORS and outlives(owner):
                # super().pop() and friends act on the instance
                match owner:
                    case ast.Call(func=ast.Name(id="super")):
                        continue
                return True
    return False


BODIES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.GeneratorExp)


def is_body(node):
    return isinstance(node, BODIES)


def first_line(node):
    """The line the compiler gives the code object of a body."""
    above = getattr(node, "decorator_list", None)
    return above[0].lineno if above else node.lineno


def outermost_bodies(tree):
    """Functions, lambdas and generator expressions that are not inside another one."""
    waiting = [tree]
    while waiting:
        for child in ast.iter_child_nodes(waiting.pop()):
            if isinstance(child, BODIES):
                yield child
                # decorators and defaults are evaluated outside the body
                if not isinstance(child, ast.GeneratorExp):
                    waiting.extend(getattr(child, "decorator_list", ()))
                    waiting.append(child.args)
            else:
                waiting.append(child)
