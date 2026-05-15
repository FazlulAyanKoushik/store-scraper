from bs4 import BeautifulSoup
import io

def analyze_html(filepath, output_filepath):
    with io.open(output_filepath, 'w', encoding='utf-8') as out:
        out.write(f"Reading {filepath}...\n")
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()
        
        soup = BeautifulSoup(html, 'html.parser')
        out.write("Parsing complete.\n")
        
        # 1. Search for 'すべて' (Show all) to see if there's a catalog button.
        show_all_texts = soup.find_all(string=lambda text: text and 'すべて' in text)
        out.write(f"Found {len(show_all_texts)} elements containing 'すべて'\n")
        for el in show_all_texts[:5]:
            parent = el.parent
            out.write(f"Text: {el.strip()} | Tag: {parent.name} | Class: {parent.get('class')} | Href: {parent.get('href')}\n")
            
        out.write("-" * 50 + "\n")
        
        # 2. Search for "data-attrid"
        attr_ids = soup.find_all(attrs={'data-attrid': True})
        out.write(f"Found {len(attr_ids)} elements with data-attrid\n")
        for el in attr_ids:
            attr_id = el.get('data-attrid')
            if 'product' in attr_id.lower() or 'catalog' in attr_id.lower() or 'local' in attr_id.lower():
                out.write(f"Relevant data-attrid: {attr_id}\n")
                texts = [text for text in el.stripped_strings]
                out.write(f"  Content summary: {texts[:5]}...\n")

        out.write("-" * 50 + "\n")
        
        # 3. Look for elements containing "商品" (product)
        products_texts = soup.find_all(string=lambda text: text and '商品' in text)
        out.write(f"Found {len(products_texts)} elements containing '商品'\n")
        for el in products_texts[:5]:
            parent = el.parent
            out.write(f"Text: {el.strip()} | Tag: {parent.name} | Class: {parent.get('class')}\n")
            
        out.write("-" * 50 + "\n")
        
        # 4. Search for specific elements that look like a product card
        common_classes = ['OSrXXb', 'BFOCWc', 'sh-pr', 'lpc']
        for cls in common_classes:
            elements = soup.find_all(class_=lambda x: x and cls in x.split())
            out.write(f"Class {cls}: {len(elements)} found\n")
            if elements:
                out.write(f"  Example texts: {[el.get_text(strip=True) for el in elements[:5]]}\n")
                
        out.write("-" * 50 + "\n")
        
        # 5. Let's look for specific tags representing list items or image links with price, maybe a carousel
        out.write("Searching for carousel elements...\n")
        carousels = soup.find_all('g-scrolling-carousel')
        out.write(f"Found {len(carousels)} carousels\n")
        for i, c in enumerate(carousels):
            out.write(f"Carousel {i}:\n")
            for j, item in enumerate(c.find_all('a')):
                if j >= 5: break
                text = item.get_text(separator=' ', strip=True)
                out.write(f"  Item {j} text: {text}\n")
                
if __name__ == '__main__':
    analyze_html('debug.txt', 'analysis_output.txt')
