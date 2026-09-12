def split_return_summary(values: list[float]) -> dict:
    if not values: return {"firstHalf":None,"secondHalf":None,"difference":None}
    middle=(len(values)+1)//2; first=sum(values[:middle])/middle; second_values=values[middle:]
    second=sum(second_values)/len(second_values) if second_values else first
    return {"firstHalf":round(first,3),"secondHalf":round(second,3),"difference":round(second-first,3)}
