from Main.celery import app
from Main.models import ProductData, Product


@app.task(name='add_product_data', bind=True)
def add_product_data(*args, **kwargs):
    product_id = kwargs.get("product_id")
    for line in kwargs.get("text").splitlines():
        product_data = ProductData(
            product_id=product_id,
            data=line
        )
        product_data.save()
        product = Product.objects.get(id=product_id)
        product.in_stock += 1
        product.save()
    return True
