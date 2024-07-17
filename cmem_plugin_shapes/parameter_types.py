"""parameter types"""

from typing import Any

from cmem.cmempy.dp.proxy.graph import get_graphs_list
from cmem_plugin_base.dataintegration.context import PluginContext
from cmem_plugin_base.dataintegration.types import Autocompletion, StringParameterType
from cmem_plugin_base.dataintegration.utils import setup_cmempy_user_access
from validators import url


class GraphParameterTypeNew(StringParameterType):
    """Knowledge Graph parameter type."""

    allow_only_autocompleted_values: bool = False
    autocomplete_value_with_labels: bool = True
    classes: set[str] | None = None

    def __init__(  # noqa: PLR0913
        self,
        show_di_graphs: bool = False,
        show_system_graphs: bool = False,
        show_graphs_without_class: bool = False,
        classes: list[str] | None = None,
        allow_only_autocompleted_values: bool = True,
    ):
        """Knowledge Graph parameter type.

        :param show_di_graphs: show DI project graphs
        :param show_system_graphs: show system graphs such as shape and query catalogs
        :param classes: allowed classes of the shown graphs
            - if None -> defaults to di:Dataset and void:Dataset
        :param allow_only_autocompleted_values: allow entering new graph URLs
        """
        self.show_di_graphs = show_di_graphs
        self.show_system_graphs = show_system_graphs
        self.show_graphs_without_class = show_graphs_without_class
        self.allow_only_autocompleted_values = allow_only_autocompleted_values
        if classes:
            self.classes = set(classes)
        else:
            self.classes = {
                "https://vocab.eccenca.com/di/Dataset",
                "http://rdfs.org/ns/void#Dataset",
            }

    def autocomplete(  # noqa: C901
        self,
        query_terms: list[str],
        depend_on_parameter_values: list[Any],  # noqa: ARG002
        context: PluginContext,
    ) -> list[Autocompletion]:
        """Autocomplete"""
        setup_cmempy_user_access(context=context.user)
        graphs = get_graphs_list()
        result = []
        for _ in graphs:
            iri = _["iri"]
            title = _["label"]["title"]
            label = f"{title} ({iri})"
            assigned_classes = set(_["assignedClasses"])
            # ignore DI project graphs
            if self.show_di_graphs is False and _["diProjectGraph"]:
                continue
            # ignore system resource graphs
            if self.show_system_graphs is False and _["systemResource"]:
                continue
            # show graphs without assigned classes only if explicitly wanted
            if not assigned_classes:
                if self.show_graphs_without_class:
                    result.append(Autocompletion(value=iri, label=label))
                continue
            # ignore graphs which do not match the requested classes
            if (
                self.classes
                and assigned_classes
                and not self.classes.intersection(assigned_classes)
            ):
                continue
            str_match = True
            for term in query_terms:
                if term.lower() not in label.lower():
                    str_match = False
                    break
            if str_match:
                result.append(Autocompletion(value=iri, label=label))
        if not result and len(query_terms) == 1 and url(query_terms[0]):
            result.append(
                Autocompletion(value=query_terms[0], label=f"new graph: {query_terms[0]}")
            )

        result.sort(key=lambda x: x.label)
        return list(set(result))
