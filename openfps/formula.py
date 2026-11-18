"""Évaluateur de formules sûr (pas d'eval() brut).

Les fichiers de jeu décrivent chaque réglage par une formule, par exemple
``clamp(round(4 + gpu * 0.10), 4, 16)``. Seuls les opérateurs arithmétiques,
les comparaisons, les conditions ``a if c else b`` et quelques fonctions
mathématiques sont autorisés : un fichier de jeu ne peut donc pas exécuter
de code arbitraire.
"""

from __future__ import annotations

import ast
import math
import operator

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_CMP = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


FUNCTIONS = {
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "sqrt": math.sqrt,
    "log2": math.log2,
    "clamp": _clamp,
}

_MAX_POW = 64


class FormulaError(ValueError):
    pass


def evaluate(expr: str, variables: dict):
    """Évalue ``expr`` avec ``variables``. Lève FormulaError si non autorisé."""
    try:
        tree = ast.parse(str(expr).strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"formule invalide: {expr!r} ({exc.msg})") from exc
    return _eval(tree.body, variables)


def _eval(node, env):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)):
            return node.value
        raise FormulaError("constante non autorisée")
    if isinstance(node, ast.Name):
        if node.id in ("true", "True"):
            return True
        if node.id in ("false", "False"):
            return False
        if node.id in env:
            return env[node.id]
        raise FormulaError(f"variable inconnue: {node.id}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
            raise FormulaError("exposant trop grand")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, env))
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise FormulaError("comparaison non autorisée")
            right = _eval(comp, env)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise FormulaError("fonction non autorisée")
        if node.keywords:
            raise FormulaError("arguments nommés non autorisés")
        return FUNCTIONS[node.func.id](*[_eval(a, env) for a in node.args])
    raise FormulaError(f"expression non autorisée: {type(node).__name__}")
