# Fancontrol feature

I want to ensure optimal air humidity for my plant within a closed up tent. For this I have mounted a fan that can be controlled with a gpio pin. For sensors I have two mqtt based sensors that read every 1h the humidity once. The fans should aim for 70% air humidity as an average between all the mqtt sensors that are attached. For handling the delayed control use a clever approach.

When implementing the feature I want a slider for the target air humidity value. Implement it in its own class like the hydro.py for the watering controll. I also need some unit tests for the new feature.
