from qgis.core import QgsExpression, QgsFeatureRequest

from .service_utils import sort_and_limit_rows


def query_attributes(layer_service, layer_id=None, layer_name=None, filters=None, fields=None, limit=50, order_by=None, select_on_map=True, zoom_to_selection=False):
    try:
        layer = layer_service.require_vector_layer(layer_id=layer_id, layer_name=layer_name)
        request = QgsFeatureRequest()
        if filters:
            expression = QgsExpression(filters)
            if expression.hasParserError():
                return layer_service.error(expression.parserErrorString())
            request.setFilterExpression(filters)

        if order_by and order_by != "feature_id" and layer.fields().indexFromName(order_by) < 0:
            return layer_service.error(f"Field not found: {order_by}")

        requested_fields = fields or [field.name() for field in layer.fields()]
        if isinstance(requested_fields, str):
            requested_fields = [requested_fields]

        collected = []
        for feature in layer.getFeatures(request):
            row = {"feature_id": feature.id()}
            for field_name in requested_fields:
                if field_name in feature.fields().names():
                    row[field_name] = feature[field_name]

            sort_value = None
            if order_by == "feature_id":
                sort_value = feature.id()
            elif order_by:
                sort_value = feature[order_by]

            collected.append(
                {
                    "row": row,
                    "feature_id": feature.id(),
                    "bbox": feature.geometry().boundingBox() if feature.hasGeometry() else None,
                    "order_value": sort_value,
                }
            )

        collected = sort_and_limit_rows(collected, order_by="order_value" if order_by else None, limit=limit)

        records = [entry["row"] for entry in collected]
        selected_ids = [entry["feature_id"] for entry in collected]
        extent = None
        for entry in collected:
            bbox = entry.get("bbox")
            if bbox is None:
                continue
            if extent is None:
                extent = bbox
            else:
                extent.combineExtentWith(bbox)

        if select_on_map:
            layer_service.call_in_main_thread(layer.selectByIds, selected_ids)
        if zoom_to_selection and extent and layer_service.iface:
            extent.scale(1.1)
            layer_service.call_in_main_thread(layer_service.iface.mapCanvas().setExtent, extent)
            layer_service.call_in_main_thread(layer_service.iface.mapCanvas().refresh)

        return layer_service.success(
            "Attribute query completed",
            data={
                "records": records,
                "match_count": len(records),
                "fields": requested_fields,
                "selected_feature_ids": selected_ids,
                "zoomed": bool(zoom_to_selection and extent),
            },
            artifacts={"layer": layer_service.artifact_for_layer(layer)},
            **layer_service.artifact_for_layer(layer),
        )
    except Exception as exc:
        return layer_service.error(str(exc))
